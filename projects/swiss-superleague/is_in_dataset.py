import pandas as pd
c = pd.read_csv("data/transfermarkt/competitions.csv")
print(c[c["country_name"].str.contains("Switz", na=False)][
    ["competition_id", "name", "type", "country_name"]])