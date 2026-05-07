import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import tsunami_warning_service as svc
from app.api.tsunami import get_current_warnings


def test_tsunami_warning_current_api_shape():
    body = asyncio.run(get_current_warnings(mock="advisory"))

    assert body["status"] in {"active", "none", "stale", "error"}
    assert body["source"] == "mock"
    assert isinstance(body["ttl_seconds"], int)
    assert isinstance(body["areas"], list)


def test_tsunami_warning_current_api_accepts_lat_lon():
    body = asyncio.run(get_current_warnings(lat=35.6, lon=139.7, mock="warning"))

    assert body["status"] == "active"
    assert body["areas"][0]["level"] == "warning"


def test_tsunami_warning_mock_levels():
    cases = {
        "major_warning": ("active", "大津波警報"),
        "warning": ("active", "津波警報"),
        "advisory": ("active", "津波注意報"),
        "none": ("none", None),
        "stale": ("stale", "津波警報"),
        "error": ("error", None),
    }

    for mock, (status, label) in cases.items():
        body = asyncio.run(get_current_warnings(mock=mock))
        assert body["status"] == status
        assert body["source"] == "mock"
        assert isinstance(body["areas"], list)
        assert isinstance(body["ttl_seconds"], int)
        if label:
            assert body["areas"][0]["level_label"] == label


def test_jma_xml_client_parses_vtse41(monkeypatch):
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>津波警報・注意報・予報 VTSE41</title>
        <link href="https://example.test/vtse41.xml" />
      </entry>
    </feed>
    """.encode("utf-8")
    report = """<?xml version="1.0" encoding="UTF-8"?>
    <Report xmlns="http://xml.kishou.go.jp/jmaxml1/">
      <Control><Title>津波警報・注意報・予報</Title></Control>
      <Head>
        <Title>津波警報・注意報・予報</Title>
        <InfoType>発表</InfoType>
        <ReportDateTime>2026-05-07T13:00:00+09:00</ReportDateTime>
      </Head>
      <Body>
        <Tsunami>
          <Forecast>
            <Item>
              <Area><Name>東京湾内湾</Name><Code>191</Code></Area>
              <Category><Kind><Name>津波警報</Name></Kind></Category>
              <FirstHeight><ArrivalTime>ただちに津波来襲と予測</ArrivalTime></FirstHeight>
              <MaxHeight><TsunamiHeight>1m</TsunamiHeight></MaxHeight>
            </Item>
          </Forecast>
        </Tsunami>
      </Body>
    </Report>
    """.encode("utf-8")

    def fake_get_bytes(url, timeout=10.0):
        return report if url.endswith("vtse41.xml") else feed

    monkeypatch.setattr(svc, "_http_get_bytes", fake_get_bytes)

    body = svc.JmaXmlTsunamiWarningClient(feed_urls=["https://example.test/feed.xml"]).fetch()

    assert body["source"] == "jma_xml"
    assert body["status"] == "active"
    assert body["areas"][0]["name"] == "東京湾内湾"
    assert body["areas"][0]["level"] == "warning"
    assert body["areas"][0]["expected_height"] == "1m"


def test_tsunami_warning_falls_back_to_p2p(monkeypatch):
    class BadClient:
        source = "jma_xml"

        def fetch(self):
            raise RuntimeError("jma unavailable")

    class GoodClient:
        source = "p2p_fallback"

        def fetch(self):
            return {
                "source": "p2p_fallback",
                "status": "none",
                "observed_at": None,
                "updated_at": "2026-05-07T13:00:00+09:00",
                "ttl_seconds": 60,
                "areas": [],
                "message": "",
            }

    monkeypatch.setattr(svc, "_cache", None)
    monkeypatch.setattr(svc, "_cache_at", 0.0)
    monkeypatch.setattr(svc, "_ENABLE_FALLBACK", True)
    monkeypatch.setattr(svc, "_clients_for_priority", lambda: [BadClient(), GoodClient()])

    body = asyncio.run(svc.get_tsunami_warnings())

    assert body["source"] == "p2p_fallback"
    assert body["status"] == "none"
