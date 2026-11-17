def test_config_exposes_valid_support_email(client, monkeypatch):
    monkeypatch.setenv('SUPPORT_EMAIL', ' help@xingji.app ')
    c, _ = client
    body = c.get('/api/config').json()
    assert body['support_email'] == 'help@xingji.app'


def test_config_hides_missing_or_invalid_support_email(client, monkeypatch):
    monkeypatch.delenv('SUPPORT_EMAIL', raising=False)
    c, _ = client
    assert c.get('/api/config').json()['support_email'] == ''

    monkeypatch.setenv('SUPPORT_EMAIL', 'not-an-email')
    body = c.get('/api/config').json()
    assert body['support_email'] == ''

def test_config_exposes_operator_when_configured(client, monkeypatch):
    monkeypatch.setenv('OPERATOR_NAME', ' 杭州行迹科技有限公司 ')
    monkeypatch.setenv('OPERATOR_CONTACT_EMAIL', ' legal@xingji.example ')
    monkeypatch.setenv('OPERATOR_JURISDICTION', '杭州市西湖区')
    monkeypatch.setenv('ICP_NUMBER', '浙ICP备2026000000号')
    c, _ = client
    body = c.get('/api/config').json()
    assert body['operator'] == {
        'name': '杭州行迹科技有限公司',
        'contact_email': 'legal@xingji.example',
        'jurisdiction': '杭州市西湖区',
        'icp_number': '浙ICP备2026000000号',
    }


def test_config_keeps_demo_operator_empty_and_hides_invalid_contact(client, monkeypatch):
    for key in ('OPERATOR_NAME', 'OPERATOR_CONTACT_EMAIL', 'OPERATOR_JURISDICTION', 'ICP_NUMBER'):
        monkeypatch.delenv(key, raising=False)
    c, _ = client
    body = c.get('/api/config').json()
    assert body['operator'] == {
        'name': '',
        'contact_email': '',
        'jurisdiction': '',
        'icp_number': '',
    }

    monkeypatch.setenv('OPERATOR_NAME', 'Example Co.')
    monkeypatch.setenv('OPERATOR_CONTACT_EMAIL', 'not-an-email')
    body = c.get('/api/config').json()
    assert body['operator']['name'] == 'Example Co.'
    assert body['operator']['contact_email'] == ''
