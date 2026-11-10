import io
from datetime import date

import pytest

from cloud_cost_anomaly.loader import UNTAGGED, CostFileError, read_costs


def parse(text):
    return read_costs(io.StringIO(text))


def test_reads_rows():
    rows = parse("date,service,account,tag,cost\n2025-03-01,EC2,prod,team=web,12.50\n")
    assert len(rows) == 1
    row = rows[0]
    assert (row.day, row.service, row.account, row.tag, row.cost) == (
        date(2025, 3, 1), "EC2", "prod", "team=web", 12.5,
    )


def test_column_order_case_and_extra_columns_do_not_matter():
    rows = parse("Cost,Region,Account,Date,Service,Tag\n3,us-east-1,dev,2025-03-01,S3,x\n")
    assert rows[0].service == "S3" and rows[0].cost == 3.0


def test_empty_or_missing_tag_becomes_untagged():
    assert parse("date,service,account,tag,cost\n2025-03-01,EC2,prod,,1\n")[0].tag == UNTAGGED
    assert parse("date,service,account,cost\n2025-03-01,EC2,prod,1\n")[0].tag == UNTAGGED


def test_blank_lines_are_skipped_and_credits_allowed():
    rows = parse("date,service,account,tag,cost\n\n2025-03-01,EC2,prod,,-4.2\n,,,,\n")
    assert [r.cost for r in rows] == [-4.2]


def test_missing_column_is_reported():
    with pytest.raises(CostFileError, match="account"):
        parse("date,service,cost\n2025-03-01,EC2,1\n")


@pytest.mark.parametrize(
    "line, message",
    [
        ("03/01/2025,EC2,prod,,1", "line 2: date"),
        ("2025-03-01,EC2,prod,,abc", "line 2: cost"),
        ("2025-03-01,EC2,prod,,nan", "finite"),
    ],
)
def test_bad_values_name_the_line(line, message):
    with pytest.raises(CostFileError, match=message):
        parse("date,service,account,tag,cost\n" + line + "\n")


def test_empty_file():
    with pytest.raises(CostFileError, match="empty"):
        parse("")
