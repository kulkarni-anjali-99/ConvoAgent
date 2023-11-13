from ibm_watson import NaturalLanguageUnderstandingV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_watson.natural_language_understanding_v1 import Features, ClassificationsOptions, KeywordsOptions
import app


def classify(sentence):
    natural_language_understanding = app.config['ibm_client']
    response = natural_language_understanding.analyze(
        text=sentence,
        features=Features(classifications=ClassificationsOptions(model='tone-classifications-en-v1'))).get_result()

    result = {}

    for emotion in response['classifications'] :
        result[emotion['class_name']] = emotion['confidence']

    return result

def extract_keywords(conversation):
    natural_language_understanding = app.config['ibm_client']
    response = natural_language_understanding.analyze(
        text=conversation,
        features=Features(keywords=KeywordsOptions(sentiment=True,emotion=True,limit=2))).get_result()
    
    result = []

    for emotion in response['keywords'] :
        result.append(emotion['text'])

    return result

