import pytest

from wrsr_installer.ui.install_dialog import pretty_type
from wrsr_installer.ui.text import ago, format_bbcode


@pytest.mark.parametrize('seconds, expected', [
    (30, 'just now'),
    (60, '1 minute ago'),
    (125, '2 minutes ago'),
    (3600, '1 hour ago'),
    (5 * 3600 + 59, '5 hours ago'),
    (86400, '1 day ago'),
    (2 * 86400 + 5, '2 days ago'),
])
def test_ago(seconds, expected):
    assert ago(seconds) == expected


@pytest.mark.parametrize('item_type, expected', [
    ('BUILDINGSKIN', 'Building skin'),
    ('VEHICLE_SKIN', 'Vehicle skin'),
    ('ROAD', 'Road'),
    ('SKIN', 'Skin'),
])
def test_pretty_type(item_type, expected):
    assert pretty_type(item_type) == expected


def test_format_bbcode_escapes_html():
    assert format_bbcode('<b>not bold</b> & co') == '&lt;b&gt;not bold&lt;/b&gt; &amp; co'


def test_format_bbcode_converts_common_tags():
    assert format_bbcode('[h1]Title[/h1]\n[b]bold[/b] [i]it[/i] [u]u[/u]') == \
        '<h3>Title</h3><b>bold</b> <i>it</i> <u>u</u>'


def test_format_bbcode_keeps_only_web_links():
    assert format_bbcode('[url=https://example.com/a?b=1&c=2]guide[/url] [url=javascript:x]bad[/url]') == \
        '<a href="https://example.com/a?b=1&amp;c=2">guide</a> bad'


def test_format_bbcode_builds_lists_and_line_breaks():
    assert format_bbcode('Contents:\n[list]\n[*]one\n[*]two\n[/list]\nEnd\nline') == \
        'Contents:<ul><li>one</li><li>two</li></ul>End<br>line'


def test_format_bbcode_drops_images():
    assert format_bbcode('x[img]http://i.example/p.png[/img]y') == 'xy'
