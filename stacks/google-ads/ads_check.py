#!/usr/bin/env python3
"""ads_check.py – reine Leseabfrage auf das Google-Ads-Konto (Etappe 1a).

GAQL: Kontoname, Waehrung, Zeitzone; Kampagnen mit id, name, status, Kanaltyp,
Tagesbudget. Ausgabe: Anzahl Kampagnen nach Status und die Liste.
Keine schreibenden Aufrufe. Fehler von Google verstaendlich, ohne Tokens.

Aufruf (SSH-Session da-hub oder per ssh aus Claude Code):
  ~/stacks/google-ads/venv/bin/python ~/stacks/google-ads/ads_check.py
"""
import collections
import sys

import ads_common as ac

GAQL_KONTO = """
    SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone
    FROM customer"""
GAQL_KAMPAGNEN = """
    SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
           campaign_budget.amount_micros
    FROM campaign
    ORDER BY campaign.id"""


def abfrage(service, kunde, gaql):
    return [z for batch in service.search_stream(customer_id=kunde, query=gaql) for z in batch.results]


def main():
    try:
        k = ac.konfig()
        client = ac.ads_client(k)
        svc = client.get_service("GoogleAdsService")
        kunde = k["customer_id"]
        konto = abfrage(svc, kunde, GAQL_KONTO)
        kampagnen = abfrage(svc, kunde, GAQL_KAMPAGNEN)
    except Exception as e:
        print("FEHLER:", ac.fehler_text(e))
        return 1

    c = konto[0].customer if konto else None
    wae = c.currency_code if c else "?"
    print(f"Konto {kunde}: «{c.descriptive_name if c else '?'}», Waehrung {wae}, Zeitzone {c.time_zone if c else '?'}")
    zaehler = collections.Counter(z.campaign.status.name for z in kampagnen)
    print(f"Kampagnen: {len(kampagnen)} – " + (", ".join(f"{s} {n}" for s, n in sorted(zaehler.items())) or "keine"))
    for z in kampagnen:
        budget = z.campaign_budget.amount_micros / 1_000_000 if z.campaign_budget.amount_micros else 0
        print(f"  {z.campaign.id:>12} | {z.campaign.status.name:8s} | {z.campaign.advertising_channel_type.name:14s} "
              f"| {budget:9.2f} {wae}/Tag | {z.campaign.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
