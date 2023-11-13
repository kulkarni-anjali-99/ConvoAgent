from flask import Flask, request, Response, json, send_from_directory
import os
import pymongo
import datetime
from flask_cors import cross_origin

from service import ibm_classification
from db.config import load_config

from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize, sent_tokenize

app = Flask(__name__, static_folder='build', static_url_path='')

config = load_config()
mongo_client = config['mongo_client']
app.config['ibm_client'] = config['ibm_client']


# Serve React App
@app.route('/', defaults={'path': ''})
# @app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')


@app.route('/create-meeting')
def login():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/get-summary')
def getSummary():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/createMeeting', methods=["POST"])
@cross_origin()
def createMeeting():
    req_data = request.json
    meetingName = str(req_data.get("meetingName"))
    taskId = int(req_data.get("taskId"))

    collection_names = mongo_client.list_collection_names()

    if len(collection_names) == 1 and collection_names[0] == "consent":
        meetingId = 1  # assign meeting id as 1 if collection has only "consent"
    else:
        meetingId = max([int(name)
                        for name in collection_names if name != "consent" and name.isdigit()]) + 1
    # Create a new collection for this meeting and set it to active
    if str(meetingId).isdigit():
        collection = mongo_client[str(meetingId)]

    records = [{"active": True}, {"taskId": taskId,
                                  "participants": [],
                                  "type": "metadata", 'meetingName':meetingName}]
    collection.insert_many(records)
    return Response(
        response=json.dumps({'success': True, 'meetingId': str(meetingId)}),
        status=200,
        mimetype="application/json"
    )


@app.route('/activeParticipants', methods=["GET"])
@cross_origin()
def get_active_participants():
    meeting_id = request.args.get("meetingId")
    meeting_collection = mongo_client[str(meeting_id)]

    inactivity_threshold = 5
    all_participants = list(meeting_collection.find(
        {"type": "ping"}).sort("pingCount", pymongo.ASCENDING))
    active_participant_netids = []

    # if there are multiple participants, check ping count difference to determine if anyone has dropped
    if len(all_participants) > 1:
        max_ping_count = all_participants[-1]['pingCount']
        for participant in all_participants:
            # participant dropped
            if max_ping_count - participant['pingCount'] >= inactivity_threshold:
                meeting_collection.delete_one(
                    {"type": "ping", "netId": participant["netId"]})
            # participant is active
            else:
                active_participant_netids.append(participant["netId"])
    elif len(all_participants) == 1:
        active_participant_netids = [all_participants[0]["netId"]]

    consent_collection = mongo_client["consent"]

    query = {"meetingId": meeting_id}
    records = list(consent_collection.find(query))

    # map names to netids
    active_participants = {}
    for entry in records:
        if entry["netId"] in active_participant_netids:
            active_participants[entry["netId"]
                                ] = entry["firstName"] + " " + entry["lastName"]

    # Return netIds of participants
    return Response(
        response=json.dumps(active_participants),
        status=200,
        mimetype="application/json"
    )


@app.route('/userconsent', methods=["POST"])
@cross_origin()
def consent():
    req_data = request.json
    firstName = req_data.get("firstName")
    lastName = req_data.get("lastName")
    netId = req_data.get("netId")
    meetingId = req_data.get("meetingId")

    # Check if meetingId exists and is active
    meeting_collection = mongo_client[meetingId]
    if meetingId not in mongo_client.list_collection_names():
        return Response(
            response=json.dumps({'success': False}),
            status=300,
            mimetype="application/json"
        )
    else:
        data = list(meeting_collection.find({"active": True}))
        if not data:
            return Response(
                response=json.dumps({'success': False}),
                status=300,
                mimetype="application/json"
            )

    query = {"taskId": {"$exists": True}, "participants": {
        "$exists": True}, "type": {"$eq": "metadata"}}
    record = meeting_collection.find_one(query)

    # Insert participant into the list of participants for a meeting only if they were not previously inserted
    if netId not in list(record["participants"]):
        update_query = {"$push": {"participants": netId}}
        meeting_collection.update_one(query, update_query)
        participantId = len(record["participants"])
    else:
        participantId = record["participants"].index(netId)

    # Insert participant into consent collection
    consent_collection = mongo_client["consent"]
    consent_collection.insert_one(
        {"firstName": firstName, "lastName": lastName, "netId": netId, "meetingId": meetingId})

    return Response(
        response=json.dumps({"success": True,
                             "taskId": record["taskId"],
                             "participantId": participantId}),
        status=200,
        mimetype="application/json"
    )


@app.route('/submitChoices', methods=["POST"])
@cross_origin()
def submit_choices():
    req_data = request.json
    netId = req_data.get('netId')
    meetingId = req_data.get('meetingId')
    choices = req_data.get('choices')
    timestamp = req_data.get("timestamp")
    isGroup = req_data.get('isGroup')
    collection = mongo_client[str(meetingId)]

    submissionType = 'groupChoices' if isGroup else 'choices'

    # Push text to DB
    collection.insert_one(
        {"netId": netId, "choices": choices, "timestamp": timestamp, "type": submissionType})

    return Response(
        response=json.dumps({'success': True}),
        status=200,
        mimetype="application/json"
    )


@app.route('/submitReady', methods=["POST"])
@cross_origin()
def submit_ready():
    req_data = request.json
    netId = req_data.get('netId')
    meetingId = req_data.get('meetingId')
    isGroup = req_data.get('isGroup')
    collection = mongo_client[str(meetingId)]

    submissionType = 'groupReady' if isGroup else 'ready'

    # Push text to DB
    collection.insert_one({"netId": netId, "type": submissionType})

    return Response(
        response=json.dumps({'success': True}),
        status=200,
        mimetype="application/json"
    )


# This API denotes that the participant claims that they have reached consensus
# and is ready to submit the group outcome
@app.route('/getGroupReadyParticipants', methods=["GET"])
@cross_origin()
def get_group_ready_participants():
    meetingId = str(request.args.get("meetingId"))
    collection = mongo_client[meetingId]
    query = {"type": {"$eq": "groupReady"}}
    records = list(collection.find(query))

    # get netids of participants that have submitted rankings
    netIds = []
    for entry in records:
        if entry["netId"] not in netIds:
            netIds.append(entry["netId"])

    consent_collection = mongo_client["consent"]

    query = {"meetingId": meetingId}
    records = list(consent_collection.find(query))

    # map names to netids
    netIds_to_names = {}
    for entry in records:
        if entry["netId"] in netIds:
            netIds_to_names[entry["netId"]
                            ] = entry["firstName"] + " " + entry["lastName"]

    return Response(
        response=json.dumps(netIds_to_names),
        status=200,
        mimetype="application/json"
    )


@app.route('/submittedParticipants', methods=["GET"])
@cross_origin()
def submitted_participants():
    meetingId = str(request.args.get("meetingId"))
    collection = mongo_client[meetingId]
    metadataQuery = {"taskId": {"$exists": True}, "participants": {
        "$exists": True}, "type": {"$eq": "metadata"}}
    metadataRecord = collection.find_one(metadataQuery)

    if metadataRecord["taskId"] == 0:
        # if desert task, retrieve choices
        query = {"type": {"$eq": "choices"}}
        records = list(collection.find(query))
    elif metadataRecord["taskId"] == 1:
        # if hidden info task, retrieve readiness
        query = {"type": {"$eq": "ready"}}
        records = list(collection.find(query))

    # get netids of participants that have submitted rankings
    netIds = []
    for entry in records:
        if entry["netId"] not in netIds:
            netIds.append(entry["netId"])

    consent_collection = mongo_client["consent"]

    query = {"meetingId": meetingId}
    records = list(consent_collection.find(query))

    # map names to netids
    netIds_to_names = {}
    for entry in records:
        if entry["netId"] in netIds:
            netIds_to_names[entry["netId"]
                            ] = entry["firstName"] + " " + entry["lastName"]

    return Response(
        response=json.dumps(netIds_to_names),
        status=200,
        mimetype="application/json"
    )

# This API denotes that the participant has submitted their final rankings for
# the group decision-making portion


@app.route('/getSubmittedFinalParticipants', methods=["GET"])
@cross_origin()
def submitted_final_participants():
    meetingId = str(request.args.get("meetingId"))
    collection = mongo_client[meetingId]
    query = {"type": {"$eq": "groupChoices"}}
    records = list(collection.find(query))

    # get netids of participants that have submitted rankings
    netIds = []
    for entry in records:
        if entry["netId"] not in netIds:
            netIds.append(entry["netId"])

    consent_collection = mongo_client["consent"]

    query = {"meetingId": meetingId}
    records = list(consent_collection.find(query))

    # map names to netids
    netIds_to_names = {}
    for entry in records:
        if entry["netId"] in netIds:
            netIds_to_names[entry["netId"]
                            ] = entry["firstName"] + " " + entry["lastName"]

    return Response(
        response=json.dumps(netIds_to_names),
        status=200,
        mimetype="application/json"
    )


@app.route('/participantCounts', methods=["GET"])
@cross_origin()
def participant_counts():
    meetingId = str(request.args.get("meetingId"))

    collection = mongo_client[meetingId]

    consent_collection = mongo_client["consent"]

    query = {"meetingId": meetingId}

    consentrecords = list(consent_collection.find(query))

    # get word counts and turn counts
    query = {"type": {"$eq": "data"}}
    records = list(collection.find(query))

    word_counts = {}
    turn_counts = {}
    names = {}
    # Map each netId to the number of words they have spoken and turns they have taken
    # We are treating each document in the meeting's collection as a turn
    for entry in consentrecords:
        names[entry["netId"]] = entry["firstName"] + " " + entry["lastName"]

    for entry in records:
        net_id = entry["netId"]
        num_words = len(entry["text"].split())
        if net_id not in word_counts:
            word_counts[net_id] = num_words
            turn_counts[net_id] = 1
        else:
            word_counts[net_id] += num_words
            turn_counts[net_id] += 1

    # get time silent
    query = {"type": {"$eq": "silent"}}
    records = list(collection.find(query))

    time_silent_counts = {}

    for entry in records:
        net_id = entry['netId']
        time_silent = entry['timeSilent']

        # convert time silent in seconds to mm:ss string
        seconds = str(time_silent % 60)
        mins = str(time_silent//60)

        padded_seconds = '0'*(2-len(seconds)) + seconds
        padded_mins = '0'*(2-len(mins)) + mins

        time_silent_counts[net_id] = padded_mins + ':' + padded_seconds

    # ensure that all netIds are present for each count to ensure data consistency
    all_net_ids = set()
    for net_id in word_counts.keys():
        all_net_ids.add(net_id)
    for net_id in time_silent_counts.keys():
        all_net_ids.add(net_id)

    # hardcode 0 values for any missing netIds
    for net_id in all_net_ids:
        if net_id not in word_counts.keys():
            word_counts[net_id] = 0
        if net_id not in turn_counts.keys():
            turn_counts[net_id] = 0
        if net_id not in time_silent_counts.keys():
            time_silent_counts[net_id] = '00:00'

    return Response(
        response=json.dumps({'wordCounts': word_counts,
                             'turnCounts': turn_counts,
                             'timeSilent': time_silent_counts,
                             'names': names}),
        status=200,
        mimetype="application/json"
    )


@app.route('/pollconversation', methods=["POST"])
@cross_origin()
def poll_conversation():
    req_data = request.json
    netId = req_data.get('netId')
    meetingId = req_data.get('meetingId')
    text = req_data.get('text')
    timestamp = req_data.get("timestamp")
    collection = mongo_client[str(meetingId)]

    # If text is invalid, return empty emotions
    if not text or len(text.split()) <= 3:
        return Response(
            response=json.dumps({
                'emotions': {
                    "excited": 0,
                    "frustrated": 0,
                    "impolite": 0,
                    "polite": 0,
                    "sad": 0,
                    "satisfied": 0,
                    "sympathetic": 0
                },
            }),
            status=204,
            mimetype="application/json"
        )
    else:
        # Push text to DB
        collection.insert_one(
            {"netId": netId, "text": text, "timestamp": timestamp, "type": "data"})

    # Get emotions
    result = ibm_classification.classify(text)

    return Response(
        response=json.dumps({'emotions': result}),
        status=200,
        mimetype="application/json"
    )


@app.route('/incrementPingCount', methods=["POST"])
@cross_origin()
def increment_ping_count():
    req_data = request.json
    net_id = req_data.get('netId')
    meeting_id = req_data.get('meetingId')

    collection = mongo_client[str(meeting_id)]

    query = {"type": {"$eq": "ping"}, "netId": {"$eq": net_id}}
    record = collection.find_one(query)

    # if user already has a ping count, increment it
    if record:
        update_query = {"$set": {"pingCount": record['pingCount']+1}}
        collection.update_one(query, update_query)
    # otherwise, add new ping entry
    else:
        query = {"type": "ping"}
        record = collection.find_one(query)

        # if no other ping counts exist, make ping count 1
        if not record:
            collection.insert_one(
                {"netId": net_id, "pingCount": 1, "type": "ping"})
        # otherwise, synchronize with existing ping count
        else:
            collection.insert_one(
                {"netId": net_id, "pingCount": record['pingCount'], "type": "ping"})

    return Response(
        response=json.dumps({'success': True}),
        status=200,
        mimetype="application/json"
    )


@app.route('/setTimeSilent', methods=["POST"])
@cross_origin()
def set_time_silent():
    req_data = request.json
    net_id = req_data.get('netId')
    meeting_id = req_data.get('meetingId')
    time_silent = req_data.get('newTimeSilent')

    collection = mongo_client[str(meeting_id)]

    # update the time silent for given netId
    query = {"type": {"$eq": "silent"}, "netId": {"$eq": net_id}}

    if collection.find_one(query):
        update_query = {"$set": {"timeSilent": time_silent}}
        collection.update_one(query, update_query)
    else:
        collection.insert_one(
            {"netId": net_id, "timeSilent": time_silent, "type": "silent"})

    return Response(
        response=json.dumps({'success': True}),
        status=200,
        mimetype="application/json"
    )


@app.route('/transcript', methods=["GET"])
@cross_origin()
def transcript():
    meetingId = str(request.args.get("meetingId"))

    # Query text data and sort by timestamp
    collection = mongo_client[meetingId]
    data = list(collection.find({"type": "data"}).sort(
        "timestamp", pymongo.ASCENDING))

    # Patch text together
    conversation = ""
    for d in data:
        if d['text']:
            conversation += d['netId'] + ": " + d["text"] + '\n'

    return Response(
        response=json.dumps({'transcript': conversation}),
        status=200,
        mimetype="application/json"
    )

# Call made when admin ends meeting


@app.route('/endMeeting', methods=["POST"])
@cross_origin()
def endMeeting():
    req_data = request.json
    meetingId = str(req_data.get("meetingId"))

    collection = mongo_client[meetingId]

    query = {"active": True}
    new_values = {"$set": {"active": False}}
    collection.update_one(query, new_values)

    return Response(
        response=json.dumps({'success': True}),
        status=200,
        mimetype="application/json"
    )


# Call made when participant leaves meeting
@app.route('/finish', methods=["POST"])
@cross_origin()
def finish():
    req_data = request.json
    netId = req_data.get('netId')
    meetingId = req_data.get('meetingId')

    collection = mongo_client[str(meetingId)]

    # Delete pingCounts document for given netId
    query = {"type": {"$eq": "ping"}, "netId": {"$eq": netId}}
    collection.delete_one(query)

    return Response(
        response=json.dumps({'success': True}),
        status=200,
        mimetype="application/json"
    )


@app.route('/keywords', methods=["POST"])
@cross_origin()
def keywords():
    req_data = request.json
    meetingId = req_data.get('meetingId')

    # Query text data and sort by timestamp
    collection = mongo_client[str(meetingId)]
    data = list(collection.find({"type": "data"}).sort(
        "timestamp", pymongo.ASCENDING))

    if not data:
        return Response(
            response=json.dumps({'keywords': "Meeting not found"}),
            status=404,
            mimetype="application/json"
        )

    # Patch text together
    conversation = ""
    for d in data:
        conversation += d["text"] + "\n"

    keywords = ibm_classification.extract_keywords(conversation)

    return Response(
        response=json.dumps({'keywords': keywords}),
        status=200,
        mimetype="application/json"
    )


@app.route('/summary', methods=["POST"])
@cross_origin()
def summary():
    req_data = request.json
    meetingId = req_data.get('meetingId')

    # Query text data and sort by timestamp
    collection = mongo_client[str(meetingId)]
    data = list(collection.find({"type": "data"}).sort(
        "timestamp", pymongo.ASCENDING))

    if not data:
        return Response(
            response=json.dumps({'summary': "Meeting not found"}),
            status=404,
            mimetype="application/json"
        )

    conversation = ""
    # Patch text together
    for d in data:
        conversation += d["text"] + "\n"

    sp = set(stopwords.words("english"))
    words = word_tokenize(conversation)
    freqTable = dict()

    for word in words:
        word = word.lower()
        if word in sp:
            continue
        if word in freqTable:
            freqTable[word] += 1
        else:
            freqTable[word] = 1

    sentences = sent_tokenize(conversation)
    sentenceValue = dict()

    for sentence in sentences:
        for word, freq in freqTable.items():
            if word in sentence.lower():
                if sentence in sentenceValue:
                    sentenceValue[sentence] += freq
                else:
                    sentenceValue[sentence] = freq

    sumValues = 0
    for sentence in sentenceValue:
        sumValues += sentenceValue[sentence]

    average = int(sumValues / len(sentenceValue))

    summary = ''
    for sentence in sentences:
        if (sentence in sentenceValue) and (sentenceValue[sentence] > (1.2 * average)):
            summary += " " + sentence

    return Response(
        response=json.dumps({'summary': summary}),
        status=200,
        mimetype="application/json"
    )


if __name__ == '__main__':
    app.run()
