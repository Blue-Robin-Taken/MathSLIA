import json
import plotly.express as px
import numpy as np

from scipy.stats import chi2_contingency, chi2  # https://www.geeksforgeeks.org/python/python-pearsons-chi-square-test/

with open("chess_openings_games.json", "r", encoding="utf-8") as f:
    gamesData = json.load(f)

print('Original Sample Size (includes non chess rule games): ', len(gamesData['games']))
eco_counts = {}

low_elo = {}  # 100-300
beginner_elo = {}  # 301-600
intermediate_elo = {}  # 601-1000
advanced_elo = {}  # 1001-2000
expert_elo = {}  # 2001-2700
grandmaster_elo = {}  # 2701-3000
AI_elo = {}  # 3001-4000

eloDicts = {'Low Elo': low_elo, 'Beginner Elo': beginner_elo, "Intermediate Elo": intermediate_elo,
            "Advanced Elo": advanced_elo, "Expert Elo": expert_elo, "Grandmaster Elo": grandmaster_elo,
            "AI Elo": AI_elo}

for game in gamesData['games']:
    if game['rules'] != 'chess':
        continue

    currentDict = eco_counts
    if game['rating'] < 301:
        currentDict = low_elo
    elif game['rating'] < 601:
        currentDict = beginner_elo
    elif game['rating'] < 1001:
        currentDict = intermediate_elo
    elif game['rating'] < 2001:
        currentDict = advanced_elo
    elif game['rating'] < 2501:
        currentDict = expert_elo
    elif game['rating'] < 3001:
        currentDict = grandmaster_elo
    elif game['rating'] < 4001:
        currentDict = AI_elo

    if not currentDict.get(game['eco_code']):
        currentDict[game['eco_code']] = 1
    else:
        currentDict[game['eco_code']] += 1

# print(sorted(expert_elo.items(), key=lambda item: int(-item[1])))

for dKey, dValue in eloDicts.items():
    for cKey, cValue in [x for x in dValue.items()]:
        if not cValue or cValue < 50:  # remove outliers
            dValue.pop(cKey)

currentDict = grandmaster_elo

allOpenings = []
for dKey, dValue in eloDicts.items():  # Match common / remove ones that aren't common among the others
    k = [z for z in dValue.keys()]  # keys of the inner dictionary
    for i in k:
        if i in allOpenings:
            continue
        allOpenings.append(i)  # create a list of all openings

for dKey, dValue in eloDicts.items():
    for key in allOpenings:
        if key not in dValue.keys():
            dValue[key] = 0
            # print("added key")

for dataKey, dataValue in eloDicts.items():
    dataGraph = px.bar(x=[x[0] for x in dataValue.items()], y=[x[1] for x in dataValue.items()],
                       labels={'x': 'ECO Code', 'y': 'Number of games'}, title=dataKey)
    dataGraph.update_layout(xaxis=dict(type='category', tickangle=90, automargin=True))
    dataGraph.update_xaxes(categoryorder='category descending')
    dataGraph.show()  # Uncomment to show graphs
# Keep common for all


print([len(v) for k, v in eloDicts.items()])

sortedEloDictList = [dict(sorted(v.items())) for k, v in eloDicts.items()]  # sort by eco to get it ordered

chiTestListData = [[z_ for z, z_ in v.items()] for v in sortedEloDictList]

N = 0

for x in chiTestListData:
    for y in x:
        N += y

npTable = np.array(chiTestListData)

r, c = npTable.shape

print("N: ", N)

# https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chi2_contingency.html
res = chi2_contingency(chiTestListData)
print("Statistic Value (X^2)", res.statistic)
print("P value: {:.5e}".format(res.pvalue))
print("log p: ", chi2.logsf(res.statistic, res.dof))
print("log10 p: ", chi2.logsf(res.statistic, res.dof) / np.log(10))
print("Cramer's V: ", np.sqrt(res.statistic / (N*min(r-1, c-1))))
