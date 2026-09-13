import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_web_server_topic_routes():
    s=(ROOT/"ghostea/web_server.py").read_text()
    assert 'path.endswith("/topics")' in s
    assert 'topics' in s and 'topic_id' in s
    assert 'get_topic_settings' in s and 'get_effective_settings' in s
    assert 'update_topic_settings' in s and 'clear_topic_settings' in s

def test_proxy_allows_topic_routes():
    s=(ROOT/"dashboard/api/ghostea.js").read_text()
    assert 'const topics = pathname.match' in s
    assert 'const topicSettings = pathname.match' in s
    assert 'Boolean(topics)' in s and 'Boolean(topicSettings)' in s

def test_dashboard_has_scope_selector():
    s=(ROOT/"dashboard/index.html").read_text()
    for token in ('topicContextBar','topicSelector','loadTopics','selectTopic','/topics/','Topic Settings'):
        assert token in s
