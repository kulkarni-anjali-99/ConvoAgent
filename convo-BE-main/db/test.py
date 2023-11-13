from config import load_config
import random

database = load_config()

# Creating collection
collection = database['mongo_client']['test']

item = {"_id" : str(random.randrange(1000000))}

collection.insert_one(item)
