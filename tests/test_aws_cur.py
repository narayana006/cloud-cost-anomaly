import io
from datetime import date

import pytest

from cloud_cost_anomaly.aws_cur import read_aws_cur
from cloud_cost_anomaly.cli import main
from cloud_cost_anomaly.loader import UNTAGGED, CostFileError

LEGACY = (
    "lineItem/UsageStartDate,lineItem/ProductCode,lineItem/UsageAccountId,"
    "lineItem/LineItemType,lineItem/UnblendedCost,resourceTags/user:team\n"
    "2025-03-01T00:00:00Z,AmazonEC2,111,Usage,10.5,data\n"
    "2025-03-01T01:00:00Z,AmazonEC2,111,Usage,2.5,\n"
    "2025-03-01T00:00:00Z,AmazonEC2,111,Tax,99,\n"
    "2025-03-01T00:00:00Z,AmazonS3,111,Credit,-1.25,web\n"
)

V2 = (
    "line_item_usage_start_date,line_item_product_code,line_item_usage_account_id,"
    "line_item_unblended_cost\n2025-03-02 00:00:00.000,AmazonRDS,222,7\n"
)


def parse(text, tag_key=None):
    return read_aws_cur(io.StringIO(text), tag_key)


def test_legacy_columns_skip_tax_and_keep_credits():
    rows = parse(LEGACY)
    assert [(r.service, r.cost) for r in rows] == [
        ("AmazonEC2", 10.5), ("AmazonEC2", 2.5), ("AmazonS3", -1.25),
    ]
    assert rows[0].day == date(2025, 3, 1) and rows[0].account == "111"
    assert all(r.tag == UNTAGGED for r in rows)


def test_tag_key_maps_resource_tag_column():
    rows = parse(LEGACY, tag_key="team")
    assert [r.tag for r in rows] == ["team=data", UNTAGGED, "team=web"]
    assert parse(LEGACY, tag_key="user:team")[0].tag == "team=data"


def test_cur2_column_names():
    row = parse(V2)[0]
    assert (row.day, row.service, row.account, row.cost) == (date(2025, 3, 2), "AmazonRDS", "222", 7.0)


def test_missing_columns_and_tag_are_reported():
    with pytest.raises(CostFileError, match="product code"):
        parse("lineItem/UsageStartDate,lineItem/UsageAccountId,lineItem/UnblendedCost\n")
    with pytest.raises(CostFileError, match="'env'"):
        parse(LEGACY, tag_key="env")


def test_bad_date_names_the_line():
    bad = V2.replace("2025-03-02 00:00:00.000", "yesterday")
    with pytest.raises(CostFileError, match="line 2"):
        parse(bad)


def _cur_file(tmp_path):
    lines = ["lineItem/UsageStartDate,lineItem/ProductCode,lineItem/UsageAccountId,"
             "lineItem/UnblendedCost,resourceTags/user:team"]
    for d in range(1, 21):
        lines.append(f"2025-03-{d:02d}T00:00:00Z,AmazonEC2,111,{100 + d % 3},web")
    lines.append("2025-03-21T00:00:00Z,AmazonEC2,111,100,web")
    lines.append("2025-03-21T00:00:00Z,AmazonEC2,111,500,data")
    path = tmp_path / "cur.csv"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_cli_scans_cur_file(tmp_path, capsys):
    path = _cur_file(tmp_path)
    code = main(["scan", "--source", "aws-cur", "--tag-key", "team", "--export", path,
                 "--fail-on-anomaly"])
    out = capsys.readouterr().out
    assert code == 2
    assert "| 2025-03-21 | AmazonEC2 | 111 |" in out and "`team=data`" in out


def test_cli_rejects_tag_key_without_cur(capsys):
    assert main(["scan", "--tag-key", "team", "--export", "x.csv"]) == 1
    assert "--tag-key" in capsys.readouterr().err
