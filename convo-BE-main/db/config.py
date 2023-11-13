from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_watson import NaturalLanguageUnderstandingV1
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import certifi

def load_config():
    load_dotenv()
    
    MONGO_USERNAME = os.getenv('MONGO_USERNAME')
    MONGO_PW = os.getenv("MONGO_PW")
    MONGO_CLUSTER = os.getenv("MONGO_CLUSTER")
    
    # Provide the mongodb atlas url to connect python to mongodb using pymongo
    MONGO_URL = "mongodb+srv://{}:{}@{}.uspja.mongodb.net/test?retryWrites=true&w=majority".format(MONGO_USERNAME, MONGO_PW, MONGO_CLUSTER)

    # Create a connection using MongoClient
    config = {}
    mongo_client = MongoClient(MONGO_URL, tlsCaFile = certifi.where())

    config['mongo_client'] = mongo_client['data']
    config['ibm_client'] = load_ibm_client()
    # Create database
    return config

def load_ibm_client():
    api_key = os.getenv('IBM_APIKEY')
    url = os.getenv('IBM_URL')
    authenticator = IAMAuthenticator(api_key)
    natural_language_understanding = NaturalLanguageUnderstandingV1(
        version='2021-08-01',
        authenticator=authenticator
    )
    natural_language_understanding.set_service_url(url)
    return natural_language_understanding