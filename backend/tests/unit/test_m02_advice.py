"""Synthetic identities, independently specified label-direction expectations."""
import pytest
from pydantic import ValidationError
from src.timing import advice, repository
from src.timing.advice_models import AdviceRequest

A, B = 'DB00001', 'DB00002'

def evaluate(monkeypatch, name='Ciprofloxacin', other='Sucralfate', profiles=(), foods=()):
    rows = {A: repository.DrugTimingRow(1,A,name,'4 hours',''), B:repository.DrugTimingRow(2,B,other,'400 days','')}
    monkeypatch.setattr(repository,'read_timing_data',lambda *_:(rows,{}))
    return advice.evaluate(AdviceRequest(drug_ids=[A,B], contexts=[{'drug_id':i,'profile_id':p} for i,p in profiles],foods=list(foods)))

def test_asymmetric_drug_pair_is_not_a_half_life_calculation(monkeypatch):
    out = evaluate(monkeypatch, profiles=[(A,'cipro_uk_tablet'),(B,'sucralfate_oral')])
    assert out.status == 'evaluated'
    assert [(x.subject_drug_id,x.other_id,x.direction,x.interval_hours.kind,x.interval_hours.lower,x.interval_hours.upper)
            for x in out.advice] == [(A,B,'before','range',1,2),(A,B,'after','lower_bound',4,None)]
    assert out.advice[1].interval_hours.inclusive is True
    assert all(x.source.url.endswith('/4346/smpc') for x in out.advice)

def test_selection_order_never_reverses_direction(monkeypatch):
    rows={A:repository.DrugTimingRow(1,A,'Sucralfate','',''), B:repository.DrugTimingRow(2,B,'Ciprofloxacin','','')}
    monkeypatch.setattr(repository,'read_timing_data',lambda *_:(rows,{}))
    out=advice.evaluate(AdviceRequest(drug_ids=[A,B],contexts=[{'drug_id':B,'profile_id':'cipro_uk_tablet'}, {'drug_id':A,'profile_id':'sucralfate_oral'}]))
    assert [x.subject_drug_id for x in out.advice]==[B,B]
    assert [x.direction for x in out.advice]==['before','after']

@pytest.mark.parametrize('food',['dairy_alone','calcium_drink_alone'])
def test_food_direction_and_outside_meal_scope(monkeypatch,food):
    out=evaluate(monkeypatch,profiles=[(A,'ciproxin_uk_suspension')],foods=[food])
    assert [(x.direction,x.interval_hours.lower,x.interval_hours.upper) for x in out.advice]==[('before',1,2),('after',4,None)]
    assert all(x.other_id==food and 'OUTSIDE meals' in ' '.join(x.conditions) for x in out.advice)
    assert out.status=='partially_evaluated'  # the sucralfate pair was not covered by this product profile

def test_meal_exception_does_not_generate_an_interval(monkeypatch):
    out=evaluate(monkeypatch,profiles=[(A,'ciproxin_uk_suspension')],foods=['dairy_in_meal'])
    assert out.advice==[]
    assert any(x.status=='not_applicable' for x in out.coverage)

def test_breakfast_only_before_no_invented_reverse(monkeypatch):
    out=evaluate(monkeypatch,name='Levothyroxine',profiles=[(A,'levothyroxine_us_tablet')],foods=['breakfast'])
    assert len(out.advice)==1
    a=out.advice[0]
    assert (a.direction,a.interval_hours.lower,a.interval_hours.upper)==('before',.5,1)
    assert 'empty stomach' in ' '.join(a.conditions)

def test_missing_context_and_missing_evidence_differ(monkeypatch):
    missing=evaluate(monkeypatch)
    assert missing.advice==[] and missing.status=='not_evaluated'
    assert missing.coverage[0].status=='conditions_required'
    absent=evaluate(monkeypatch,name='Unlisted synthetic agent')
    assert absent.advice==[] and absent.status=='evaluated'
    assert absent.coverage[0].status=='not_in_catalog'

@pytest.mark.parametrize('profile',['invented','levothyroxine_us_tablet'])
def test_unknown_or_mismatched_profile_rejected(monkeypatch,profile):
    with pytest.raises(ValueError):evaluate(monkeypatch,profiles=[(A,profile)])

def test_unknown_drug_and_database_error_not_empty_success(monkeypatch):
    monkeypatch.setattr(repository,'read_timing_data',lambda *_:({},{}))
    out=advice.evaluate(AdviceRequest(drug_ids=[A,B]))
    assert out.advice==[] and out.coverage[0].status=='drug_not_found'
    def fail(*_):raise repository.TimingDataUnavailable('SyntheticFailure')
    monkeypatch.setattr(repository,'read_timing_data',fail)
    with pytest.raises(repository.TimingDataUnavailable):advice.evaluate(AdviceRequest(drug_ids=[A,B]))

@pytest.mark.parametrize('body',[
    {'drug_ids':[A,A]}, {'drug_ids':[A]}, {'drug_ids':[A,B],'dose':10},
    {'drug_ids':[A,B],'contexts':[{'drug_id':'DB99999','profile_id':'x'}]},
    {'drug_ids':[A,B],'contexts':[{'drug_id':A,'profile_id':'x'},{'drug_id':A,'profile_id':'y'}]},
    {'drug_ids':[A,B],'foods':['breakfast','breakfast']}, {'drug_ids':[A,B],'foods':['unknown']},
])
def test_invalid_requests(body):
    with pytest.raises(ValidationError):AdviceRequest(**body)

def test_no_alias_or_formulation_guessing():
    assert advice.profiles_for('Cipro')==[]
    assert advice.profiles_for('Ciprofloxacin eye drops')==[]
    assert advice.profiles_for('Ciprofloxacin')
