from datetime import date, timedelta

import pytest

from cloud_cost_anomaly.detect import Settings, robust_baseline, scan
from cloud_cost_anomaly.loader import CostRow

START = date(2025, 1, 1)


def series(costs, service="EC2", account="prod", tag="team=a", start=START):
    return [
        CostRow(start + timedelta(days=i), service, account, tag, cost)
        for i, cost in enumerate(costs)
    ]


def test_robust_baseline_ignores_an_earlier_spike():
    centre, spread = robust_baseline([100, 101, 99, 100, 900, 100, 102])
    assert centre == 100
    assert spread < 10


def test_robust_baseline_floors_spread_for_flat_series():
    centre, spread = robust_baseline([50.0] * 10, min_spread_pct=5.0)
    assert centre == 50.0
    assert spread == pytest.approx(2.5)


def test_flat_series_has_no_anomalies():
    result = scan(series([100.0] * 30))
    assert result.anomalies == []
    assert result.groups_checked == 1


def test_spike_is_detected_with_baseline_and_change():
    costs = [100.0, 102.0, 98.0, 101.0, 99.0] * 4 + [400.0]
    result = scan(series(costs))
    assert len(result.anomalies) == 1
    anomaly = result.anomalies[0]
    assert anomaly.day == START + timedelta(days=20)
    assert anomaly.group == {"service": "EC2", "account": "prod"}
    assert anomaly.direction == "spike"
    assert anomaly.baseline == pytest.approx(100.0)
    assert anomaly.change == pytest.approx(300.0)
    assert anomaly.change_pct == pytest.approx(300.0)


def test_small_absolute_change_is_ignored():
    # 1.00 -> 3.00 is a big relative jump but below the default min change of 10.
    costs = [1.0] * 20 + [3.0]
    assert scan(series(costs)).anomalies == []
    assert len(scan(series(costs), Settings(min_change=1.0)).anomalies) == 1


def test_drop_only_reported_when_direction_allows():
    costs = [200.0] * 20 + [20.0]
    assert scan(series(costs)).anomalies == []
    drops = scan(series(costs), Settings(direction="down")).anomalies
    assert len(drops) == 1
    assert drops[0].direction == "drop"
    assert drops[0].change == pytest.approx(-180.0)


def test_days_limits_the_scan_window():
    costs = [100.0] * 10 + [500.0] + [100.0] * 19  # spike on day index 10
    assert len(scan(series(costs), Settings(days=30)).anomalies) == 1
    assert scan(series(costs), Settings(days=5)).anomalies == []


def test_too_little_history_is_skipped_not_flagged():
    result = scan(series([10.0, 10.0, 10.0, 900.0]))
    assert result.anomalies == []
    assert result.groups_checked == 0
    assert result.groups_skipped == 1


def test_missing_day_counts_as_zero_cost():
    rows = series([100.0] * 20)
    rows += [CostRow(START + timedelta(days=21), "EC2", "prod", "team=a", 100.0)]
    result = scan(rows, Settings(direction="down"))
    assert [a.day for a in result.anomalies] == [START + timedelta(days=20)]
    assert result.anomalies[0].cost == 0.0


def test_new_service_is_not_compared_with_days_before_it_existed():
    rows = series([100.0] * 30, service="EC2")
    rows += series([80.0] * 10, service="Bedrock", start=START + timedelta(days=20))
    result = scan(rows)
    assert result.anomalies == []


def test_contributors_name_the_tag_that_moved():
    rows = series([100.0] * 20 + [100.0], tag="team=a")
    rows += series([50.0] * 20 + [350.0], tag="team=b")
    rows += series([30.0] * 20 + [25.0], tag="team=c")  # moved the other way
    anomaly = scan(rows).anomalies[0]
    assert anomaly.cost == pytest.approx(475.0)
    assert len(anomaly.contributors) == 1
    top = anomaly.contributors[0]
    assert top.key == {"tag": "team=b"}
    assert top.cost == pytest.approx(350.0)
    assert top.baseline == pytest.approx(50.0)
    assert top.change == pytest.approx(300.0)
    assert top.share_pct == pytest.approx(300.0 / 295.0 * 100)


def test_top_limits_contributors_and_orders_by_change():
    rows = []
    for i, jump in enumerate([10.0, 200.0, 50.0, 120.0]):
        rows += series([20.0] * 20 + [20.0 + jump], tag=f"team={i}")
    anomaly = scan(rows, Settings(top=2)).anomalies[0]
    assert [c.key["tag"] for c in anomaly.contributors] == ["team=1", "team=3"]


def test_groups_are_independent():
    rows = series([100.0] * 20 + [100.0], account="prod")
    rows += series([100.0] * 20 + [600.0], account="dev")
    result = scan(rows)
    assert [a.group["account"] for a in result.anomalies] == ["dev"]
    assert result.groups_checked == 2


def test_group_by_tag_explains_with_service_and_account():
    rows = series([40.0] * 20 + [40.0], service="EC2", tag="team=a")
    rows += series([40.0] * 20 + [300.0], service="S3", tag="team=a")
    result = scan(rows, Settings(group_by=("tag",)))
    anomaly = result.anomalies[0]
    assert anomaly.group == {"tag": "team=a"}
    assert anomaly.contributors[0].key == {"service": "S3", "account": "prod"}


def test_spend_from_zero_baseline_has_no_percentage():
    rows = series([0.0] * 20 + [75.0])
    anomaly = scan(rows).anomalies[0]
    assert anomaly.change_pct is None
    assert anomaly.score == float("inf")


def test_anomalies_sorted_by_size_of_change():
    rows = series([100.0] * 20 + [300.0], service="A")
    rows += series([100.0] * 20 + [900.0], service="B")
    assert [a.group["service"] for a in scan(rows).anomalies] == ["B", "A"]


@pytest.mark.parametrize(
    "settings",
    [
        Settings(days=0),
        Settings(threshold=0),
        Settings(direction="sideways"),
        Settings(group_by=("region",)),
        Settings(group_by=()),
        Settings(min_history=20, baseline_days=10),
    ],
)
def test_invalid_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        scan(series([1.0] * 10), settings)


def test_empty_input_is_rejected():
    with pytest.raises(ValueError):
        scan([])
