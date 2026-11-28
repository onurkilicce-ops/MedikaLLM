"""Real PostgreSQL + router/auth/service/JSON, all data explicitly synthetic."""
import jwt
from datetime import datetime, timedelta, timezone
from .conftest import requires_synthetic_pg
from .test_m02_audit_http_pg import A, B, _set, _post, _auth, _reasons
from .synthetic_data import ACCOUNTS
from ..unit.test_m02_ownership_completion import NEGATIVE, POSITIVE

pytestmark=requires_synthetic_pg

def test_d3_thirteen_negative_and_eight_positive(synthetic_pg,synthetic_app):
    for text in NEGATIVE+POSITIVE:
        _set(synthetic_pg,{A:('[SYNTHETIC] Drug A',text if 'Tmax' in text else '',text if 'Tmax' not in text else ''),
                           B:('[SYNTHETIC] Drug B','','')})
        d=_post(synthetic_app,[A,B])[A]
        if text in NEGATIVE:
            assert d['measurements']==[] and d['derived']==[]
            assert 'subject_unresolved' in _reasons(d)
            item=next(i for f in d['fields'] for i in f['review_items'] if i['reason']=='subject_unresolved')
            assert text[item['quote_start']:item['quote_end']]==item['quote']
        else:
            assert d['measurements'][0]['hours']['value']==4
            assert d['measurements'][0]['review_required'] is False
            assert d['derived'][0]['hours']['value']==20

def test_search_and_advice_real_database(synthetic_pg,synthetic_app):
    _set(synthetic_pg,{A:('[SYNTHETIC] Ciprofloxacin','',''),B:('[SYNTHETIC] Sucralfate','','')})
    r=synthetic_app.get('/api/timing/drugs?q=cipro',headers=_auth())
    assert r.status_code==200
    item=r.json()['items'][0]
    assert item['drug_id']==A and len(item['profiles'])==2
    body={'drug_ids':[A,B],'contexts':[{'drug_id':A,'profile_id':'cipro_uk_tablet'}, {'drug_id':B,'profile_id':'sucralfate_oral'}]}
    r=synthetic_app.post('/api/timing/advice',json=body,headers=_auth())
    assert r.status_code==200
    assert [x['direction'] for x in r.json()['advice']]==['before','after']
    assert [x['interval_hours']['lower'] for x in r.json()['advice']]==[1,4]
    body['contexts']=[{'drug_id':A,'profile_id':'ciproxin_uk_suspension'}]
    body['foods']=['dairy_alone']
    r=synthetic_app.post('/api/timing/advice',json=body,headers=_auth())
    assert r.status_code==200 and len(r.json()['advice'])==2
    assert all(x['other_kind']=='food' for x in r.json()['advice'])
    assert synthetic_app.get('/api/timing/drugs?q=%25_',headers=_auth()).json()['items']==[]
    assert synthetic_app.get('/api/timing/drugs?q=nonexistent',headers=_auth()).json()['items']==[]

def test_new_endpoints_auth_validation_and_db_errors(synthetic_pg,synthetic_app,monkeypatch):
    from src.config import settings
    from src.timing import repository
    endpoints=[('get','/api/timing/drugs?q=DB',{}),('post','/api/timing/advice',{'json':{'drug_ids':[A,B]}})]
    patient={'Authorization':'Bearer '+jwt.encode({'userId':ACCOUNTS['patient2'][0],
             'exp':datetime.now(timezone.utc)+timedelta(hours=1)},settings.jwt_secret,algorithm='HS256')}
    for method,path,extra in endpoints:
        call=getattr(synthetic_app,method)
        assert call(path,**extra).status_code==401
        assert call(path,headers=patient,**extra).status_code==403
    assert synthetic_app.get('/api/timing/drugs?q=%20%20',headers=_auth()).status_code==422
    assert synthetic_app.post('/api/timing/advice',headers=_auth(),json={'drug_ids':[A,A]}).status_code==422
    def fail(*_):raise repository.TimingDataUnavailable('synthetic')
    monkeypatch.setattr(repository,'read_timing_data',fail)
    monkeypatch.setattr(repository,'search_drugs',fail)
    for method,path,extra in endpoints:
        r=getattr(synthetic_app,method)(path,headers=_auth(),**extra)
        assert r.status_code==503 and 'traceback' not in r.text.lower()
