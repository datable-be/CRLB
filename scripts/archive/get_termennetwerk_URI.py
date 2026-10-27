import requests
import csv
import time
from typing import List, Dict, Any
import re
import os

# Instellingen
ENDPOINT = "https://termennetwerk-api.netwerkdigitaalerfgoed.nl/graphql"
# SOURCE = "http://vocab.getty.edu/aat"
SOURCE = "https://iconclass.org"
INPUT_FILE = 'termen_te_reconcilieren.csv'
OUTPUT_FILE = re.findall(r'(.*)\.csv', INPUT_FILE)[0] + '_aat_uris.csv'

# Create the reconciled_values directory if it doesn't exist
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

QUERY = """
query GetTerms($search: String!) {
  terms(
    sources: ["%s"],
    query: $search
  ) {
    result {
      __typename
      ... on Terms {
        terms {
          uri
          prefLabel
        }
      }
      ... on Error {
        message
      }
    }
  }
}
""" % SOURCE


def fetch_terms(search_term: str) -> List[Dict[str, str]]:
    """Zoekt een term op en geeft een lijst van dictionaries met URI en Label terug."""
    payload = {
        "query": QUERY,
        "variables": {"search": search_term}
    }

    try:
        r = requests.post(ENDPOINT, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"Fout bij ophalen '{search_term}': {e}")
        return []

    results = []
    for entry in data.get('data', {}).get('terms', []):
        result_node = entry.get('result', {})
        if result_node.get('__typename') == 'Terms':
            for term in result_node.get('terms', []):
                results.append({
                    'zoekterm': search_term,
                    'uri': term.get('uri'),
                    'prefLabel': term.get('prefLabel', [None])[0]  # Pak eerste label
                })
                print(f" zoekterm: '{search_term}', uri: '{term.get('uri')}', label: '{term.get('prefLabel', [None])[0]}'")
    return results


def main():
    all_results = []

    # 1. Lees de termen uit het bronbestand
    print(f"Bezig met lezen van: {INPUT_FILE}")
    try:
        with open(INPUT_FILE, mode='r', encoding='utf-8') as f:
            # We gaan ervan uit dat de termen in de eerste kolom staan
            reader = csv.reader(f)
            # Sla de header over als die er is:
            next(reader)
            termen = [row[0] for row in reader if row]
    except FileNotFoundError:
        print(f"Bestand niet gevonden: {INPUT_FILE}")
        return

    # 2. Doorloop de termen en bevraag de API
    print(f"Totaal {len(termen)} termen gevonden. Starten met API-aanvragen...")

    for term in termen:
        print(f"Zoeken naar: {term}...", end="\r")
        found_uris = fetch_terms(term)
        all_results.extend(found_uris)
        # Optioneel: korte pauze om de API niet te overbelasten
        time.sleep(0.1)

    # 3. Schrijf alles weg naar CSV
    with open(OUTPUT_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['zoekterm', 'uri', 'prefLabel'])
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\nKlaar! {len(all_results)} resultaten weggeschreven naar {OUTPUT_FILE}")


if __name__ == "__main__":
    main()