import io
from datetime import date

import pytest

from cloud_cost_anomaly.cli import main
from cloud_cost_anomaly.gcp_billing import read_gcp_billing
from cloud_cost_anomaly.loader import UNTAGGED, CostFileError

DOTTED = (
    "usage_start_time,service.description,project.id,cost,credits,labels\n"
    '2025-03-01 08:00:00 UTC,Compute Engine,proj-a,10.00,'
    '"[{""name"": ""SUD"", ""amount"": -1.5}, {""name"": ""Promo"", ""amount"": -0.5}]",'
    '"[{""key"": ""team"", ""value"": ""data""}, {""key"": ""env"", ""value"": ""prod""}]"\n'
    "2025-03-01T09:00:00Z,Cloud Storage,proj-a,4.25,[],[]\n"
    "2025-03-02 00:00:00 UTC,Cloud Storage,proj-b,3,,\n"
)
FLAT = (
    "usage_start_time,service_description,project_id,cost\n"
    "2025-03-03T00:00:00Z,BigQuery,proj-c,7\n"
)


def parse(text, **kw):
    return read_gcp_billing(io.StringIO(text), **kw)


def test_credits_are_netted_by_default():
    rows = parse(DOTTED)
    assert [r.cost for r in rows] == [8.0, 4.25, 3.0]
    assert rows[0].day == date(2025, 3, 1)
    assert (rows[0].service, rows[0].account) == ("Compute Engine", "proj-a")
    assert all(r.tag == UNTAGGED for r in rows)


def test_ignore_credits_uses_gross_cost():
    assert parse(DOTTED, include_credits=False)[0].cost == 10.0


def test_label_key_selects_tag():
    rows = parse(DOTTED, label_key="env")
    assert [r.tag for r in rows] == ["env=prod", UNTAGGED, UNTAGGED]
    assert parse(DOTTED, label_key="team")[0].tag == "team=data"


def test_flattened_column_names():
    row = parse(FLAT)[0]
    assert (row.day, row.service, row.account, row.cost) == (date(2025, 3, 3), "BigQuery", "proj-c", 7.0)


def test_errors_are_reported():
    with pytest.raises(CostFileError, match="project.id"):
        parse("usage_start_time,service.description,cost\n2025-03-01,x,1\n")
    with pytest.raises(CostFileError, match="no 'labels' column"):
        parse(FLAT, label_key="team")
    with pytest.raises(CostFileError, match="not valid JSON"):
        parse("usage_start_time,service.description,project.id,cost,credits\n2025-03-01,x,p,1,{oops\n")
    with pytest.raises(CostFileError, match="not a date"):
        parse("usage_start_time,service.description,project.id,cost\nnope,x,p,1\n")


def test_cli_scans_gcp_sample(capsys):
    code = main(["scan", "--source", "gcp-billing", "--tag-key", "team",
                 "--export", "examples/gcp_billing_sample.csv", "--fail-on-anomaly"])
    out = capsys.readouterr().out
    assert code == 2
    assert "Compute Engine" in out and "team=data" in out


def test_cli_rejects_misused_flags(capsys):
    assert main(["scan", "--export", "examples/daily_costs.csv", "--ignore-credits"]) == 1
    assert main(["scan", "--export", "examples/daily_costs.csv", "--tag-key", "x"]) == 1
    assert "only applies" in capsys.readouterr().err
