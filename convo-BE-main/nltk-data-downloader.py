import nltk

req_file = open('nltk.txt', 'r')
Lines = req_file.readlines()

for line in Lines:
    nltk.download(line.strip())
