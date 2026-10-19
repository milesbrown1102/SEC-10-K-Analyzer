# test_institutional_holdings.py
"""
Offline tests for backend/institutional_holdings.py — pure functions only,
no SEC or OpenFIGI calls. Run with: python test_institutional_holdings.py
"""

from backend import institutional_holdings as ih

INFO_TABLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ns1:informationTable xmlns:ns1="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <ns1:infoTable>
    <ns1:nameOfIssuer>ALLY FINL INC</ns1:nameOfIssuer>
    <ns1:titleOfClass>COM</ns1:titleOfClass>
    <ns1:cusip>02005N100</ns1:cusip>
    <ns1:value>1000</ns1:value>
    <ns1:shrsOrPrnAmt><ns1:sshPrnamt>100</ns1:sshPrnamt><ns1:sshPrnamtType>SH</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>
    <ns1:votingAuthority><ns1:Sole>100</ns1:Sole><ns1:Shared>0</ns1:Shared><ns1:None>0</ns1:None></ns1:votingAuthority>
  </ns1:infoTable>
  <ns1:infoTable>
    <ns1:nameOfIssuer>ALLY FINL INC</ns1:nameOfIssuer>
    <ns1:titleOfClass>COM</ns1:titleOfClass>
    <ns1:cusip>02005N100</ns1:cusip>
    <ns1:value>500</ns1:value>
    <ns1:shrsOrPrnAmt><ns1:sshPrnamt>50</ns1:sshPrnamt><ns1:sshPrnamtType>SH</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>
  </ns1:infoTable>
  <ns1:infoTable>
    <ns1:nameOfIssuer>NVIDIA CORPORATION</ns1:nameOfIssuer>
    <ns1:titleOfClass>COM</ns1:titleOfClass>
    <ns1:cusip>67066G104</ns1:cusip>
    <ns1:value>9000</ns1:value>
    <ns1:shrsOrPrnAmt><ns1:sshPrnamt>60</ns1:sshPrnamt><ns1:sshPrnamtType>SH</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>
    <ns1:putCall>Put</ns1:putCall>
  </ns1:infoTable>
</ns1:informationTable>
"""


def _pos(cusip, name, shares, value, put_call=None):
    return {"cusip": cusip, "name": name, "put_call": put_call,
            "shares": float(shares), "value": float(value)}


def test_parse_sums_split_rows_and_separates_options():
    positions = ih.parse_information_table(INFO_TABLE_XML)
    assert set(positions) == {"02005N100", "67066G104|PUT"}, positions
    ally = positions["02005N100"]
    assert ally["shares"] == 150 and ally["value"] == 1500, ally
    assert positions["67066G104|PUT"]["put_call"] == "PUT"
    print("PASS test_parse_sums_split_rows_and_separates_options")


def test_change_classification():
    prev = {
        "A": _pos("A", "Added Co", 100, 1000),
        "T": _pos("T", "Trimmed Co", 100, 1000),
        "H": _pos("H", "Held Co", 100, 1000),
        "X": _pos("X", "Exited Co", 100, 1000),
    }
    curr = {
        "A": _pos("A", "Added Co", 150, 1500),
        "T": _pos("T", "Trimmed Co", 50, 500),
        "H": _pos("H", "Held Co", 105, 1050),
        "N": _pos("N", "New Co", 10, 2000),
    }
    by_key = {c["key"]: c for c in ih.compute_changes(prev, curr)}
    assert by_key["A"]["change_type"] == "added" and by_key["A"]["shares_change_pct"] == 50.0
    assert by_key["T"]["change_type"] == "trimmed"
    assert by_key["H"]["change_type"] == "held"
    assert by_key["X"]["change_type"] == "exited" and by_key["X"]["est_value_change"] == -1000
    assert by_key["N"]["change_type"] == "new" and by_key["N"]["shares_change_pct"] is None
    print("PASS test_change_classification")


def test_stock_split_is_not_reported_as_a_buy():
    # 10-for-1 split: shares x10, price /10, position value roughly unchanged.
    prev = {"S": _pos("S", "Split Co", 100, 100_000)}
    curr = {"S": _pos("S", "Split Co", 1000, 105_000)}
    ch = ih.compute_changes(prev, curr)[0]
    assert ch["split_adjusted"] == 10, ch
    assert ch["change_type"] == "held", ch
    print("PASS test_stock_split_is_not_reported_as_a_buy")


def test_genuine_doubling_is_not_mistaken_for_split():
    # Shares doubled at a similar price: a real purchase, not a 2:1 split.
    prev = {"D": _pos("D", "Doubled Co", 100, 10_000)}
    curr = {"D": _pos("D", "Doubled Co", 200, 21_000)}
    ch = ih.compute_changes(prev, curr)[0]
    assert ch["split_adjusted"] == 1 and ch["change_type"] == "added", ch
    print("PASS test_genuine_doubling_is_not_mistaken_for_split")


def test_split_ratio_comes_from_price_and_trading_is_kept():
    # 5:1 split (price 314 -> 66) while the manager's shares rose only 4x:
    # that's a 5:1 split plus a 20% trim, not a 4:1 split.
    prev = {"C": _pos("C", "Carvana", 1000, 314_400)}
    curr = {"C": _pos("C", "Carvana", 4000, 263_200)}
    ch = ih.compute_changes(prev, curr)[0]
    assert ch["split_adjusted"] == 5, ch
    assert ch["change_type"] == "trimmed" and ch["shares_change_pct"] == -20.0, ch
    print("PASS test_split_ratio_comes_from_price_and_trading_is_kept")


def test_values_reported_in_thousands_are_scaled():
    positions = {"G": _pos("G", "Alphabet", 1000, 357), "A": _pos("A", "Amazon", 1000, 238)}
    scaled = ih.normalize_value_units(positions)
    assert scaled["G"]["value"] == 357_000, scaled
    already_dollars = {"G": _pos("G", "Alphabet", 1000, 357_000)}
    assert ih.normalize_value_units(already_dollars)["G"]["value"] == 357_000
    print("PASS test_values_reported_in_thousands_are_scaled")


def test_consensus_counts_buyers_and_ignores_options_and_holds():
    def act(name, changes):
        return {"name": name, "error": None, "changes": changes}

    def ch(cusip, kind, put_call=None, est=100.0):
        return {"cusip": cusip, "name": cusip, "ticker": cusip, "put_call": put_call,
                "change_type": kind, "shares_change_pct": None, "weight_curr_pct": 1.0,
                "est_value_change": est}

    acts = [
        act("Fund A", [ch("MU", "new"), ch("NVDA", "added", put_call="PUT"), ch("KO", "held")]),
        act("Fund B", [ch("MU", "added"), ch("AAPL", "exited", est=-50)]),
        act("Fund C", [ch("MU", "trimmed", est=-30), ch("AAPL", "new")]),
        {"name": "Broken", "error": "boom", "changes": []},
    ]
    rows = {r["cusip"]: r for r in ih.build_consensus(acts)}
    assert "NVDA" not in rows, "options must not count as buys"
    assert "KO" not in rows, "unchanged positions are not buys or sells"
    assert rows["MU"]["buyer_count"] == 2 and rows["MU"]["seller_count"] == 1
    assert rows["MU"]["new_position_count"] == 1
    assert ih.build_consensus(acts)[0]["cusip"] == "MU", "most net buyers sorts first"
    print("PASS test_consensus_counts_buyers_and_ignores_options_and_holds")


def test_holdings_for_tickers_skips_options():
    report = {"managers": [{"name": "Fund A", "changes": [
        {"ticker": "VST", "put_call": None, "change_type": "new", "shares_change_pct": None,
         "weight_curr_pct": 2.0, "value_curr": 10.0},
        {"ticker": "VST", "put_call": "CALL", "change_type": "new", "shares_change_pct": None,
         "weight_curr_pct": 1.0, "value_curr": 5.0},
    ]}]}
    out = ih.holdings_for_tickers(report, ["vst", "NVDA"])
    assert len(out["VST"]) == 1 and out["NVDA"] == [], out
    print("PASS test_holdings_for_tickers_skips_options")


if __name__ == "__main__":
    test_parse_sums_split_rows_and_separates_options()
    test_change_classification()
    test_stock_split_is_not_reported_as_a_buy()
    test_genuine_doubling_is_not_mistaken_for_split()
    test_split_ratio_comes_from_price_and_trading_is_kept()
    test_values_reported_in_thousands_are_scaled()
    test_consensus_counts_buyers_and_ignores_options_and_holds()
    test_holdings_for_tickers_skips_options()
    print("\nAll institutional holdings tests passed.")
