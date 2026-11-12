import os
import datetime
import requests
import xml.etree.ElementTree as ET

USER_NAME = os.getenv("USER_NAME", "Pxjjuzz")
TOKEN = os.getenv("ACCESS_TOKEN") or os.getenv("GITHUB_TOKEN")
if not TOKEN:
    raise RuntimeError("Set ACCESS_TOKEN or GITHUB_TOKEN.")

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER) {
      totalCount
      edges { node { stargazers { totalCount } } }
    }
    contributionsCollection { contributionCalendar { totalContributions } }
  }
}
"""

def age_string():
    birth = datetime.date(2008, 1, 17)
    today = datetime.date.today()
    years = today.year - birth.year
    months = today.month - birth.month
    days = today.day - birth.day
    if days < 0:
        months -= 1
        previous_month = today.replace(day=1) - datetime.timedelta(days=1)
        days += previous_month.day
    if months < 0:
        years -= 1
        months += 12
    return f"{years} years, {months} months, {days} days"

def main():
    response = requests.post(
        "https://api.github.com/graphql",
        json={"query": QUERY, "variables": {"login": USER_NAME}},
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    user = payload["data"]["user"]
    repos = user["repositories"]
    stats = {
        "age_data": age_string(),
        "repo_data": f'{repos["totalCount"]:,}',
        "star_data": f'{sum(edge["node"]["stargazers"]["totalCount"] for edge in repos["edges"]):,}',
        "contrib_data": f'{user["contributionsCollection"]["contributionCalendar"]["totalContributions"]:,}',
        "follower_data": f'{user["followers"]["totalCount"]:,}',
    }
    for filename in ("dark_mode.svg", "light_mode.svg"):
        tree = ET.parse(filename)
        root = tree.getroot()
        for element in root.iter():
            element_id = element.attrib.get("id")
            if element_id in stats:
                element.text = stats[element_id]
        tree.write(filename, encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    main()
