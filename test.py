import random

players = {                                                                                                               
  'players': ['saransh', 'darian'],                                                                                       
  'playing': []                                                                                     
}

players['playing'] = list(players['players'])

randnum = random.randint(0, len(players['playing'])-1)

allplay = players['players']
print(players)
players['players'].pop(randnum)
print(players)