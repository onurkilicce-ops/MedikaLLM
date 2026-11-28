"""M-02 only, explicit throw-away database. Never starts a PostgreSQL cluster.

Run from backend/: python scripts/m02_synthetic_demo.py --seed [--serve]
Requires DO_POSTGRES_URL, M02_DEMO_CONFIRM, MEDICALLM_SYNTHETIC_PG_CONFIRM.
The existing guards must both pass before any write. --serve uses real routes,
auth, services and SQL, but disables app startup (LLM, periodic jobs/migrations).
This is a local test harness, NOT the production entry point.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', action='store_true')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=18102)
    args = parser.parse_args()
    if not (args.seed or args.serve):
        parser.error('choose --seed and/or --serve')
    from src.timing.demo_guard import check_target
    ok, messages = check_target()
    if not ok:
        print('REFUSED: ' + ' '.join(messages))
        return 2
    from tests.integration.synthetic_data import assert_safe_to_reset, reset_and_seed
    # Also checks for non-synthetic drug records, not only users.
    url = os.environ['DO_POSTGRES_URL']
    assert_safe_to_reset(url)
    if args.seed:
        reset_and_seed(url)
        from sqlalchemy import create_engine
        from tests.integration.test_m02_audit_http_pg import _set
        engine = create_engine(url)
        try:
            # IDs are fixture placeholders, NOT real mappings of these names
            # to DrugBank ids. Every field is synthetic; not clinical PK data.
            _set(engine, {
                'DB00006': ('[SYNTHETIC] Ciprofloxacin', '[SYNTHETIC] Tmax is 30-60 minutes after oral administration.',
                            '[SYNTHETIC] The half-life is 4-6 hours.[A900001]'),
                'DB00316': ('[SYNTHETIC] Sucralfate', '', '[SYNTHETIC] The half-life is 2 days.'),
                'DB00682': ('[SYNTHETIC] Levothyroxine', '', '[SYNTHETIC] The half-life is 7 days.'),
                'DB00945': ('[SYNTHETIC] Uncertain agent', '', '[SYNTHETIC] Regarding another drug, the half-life is 10 hours.'),
                'DB01211': ('[SYNTHETIC] Empty agent', '', ''),
            }, [('DB00006','A900001','[SYNTHETIC] Example source for UI checks; not a clinical reference.')])
            # M-03: SYNTHETIC protein entries and organ text (fixture data; not real
            # DrugBank enzyme/transporter records of these names).
            from tests.integration.test_m03_mechanism_api_pg import set_mechanism
            S = '[SYNTHETIC] '
            cyp = ('BE9000001', S + 'Cytochrome P450 1A2', 'Humans')
            set_mechanism(engine, {
                'DB00006': {'route': S + 'About 50% is excreted unchanged in urine and 15% in feces.',
                            'metabolism': S + 'Partly hepatic metabolism.',
                            'enzymes': [(*cyp, 'yes', 'inhibitor', 'strong')]},
                'DB00945': {'route': S + 'Mainly eliminated in bile.', 'enzymes': [(*cyp, 'yes', 'substrate')]},
            }, [('DB00006', 'DB00945', S + 'The metabolism of Uncertain agent can be decreased when combined with Ciprofloxacin.')])
        finally:
            engine.dispose()
        print('SYNTHETIC M02/M03 records seeded. These PK texts and identity mappings are not clinical data.')
    if args.serve:
        from contextlib import asynccontextmanager
        import uvicorn
        from src.main import app

        @asynccontextmanager
        async def test_lifespan(_):
            yield
        app.router.lifespan_context = test_lifespan
        print('M02 SYNTHETIC test server; LLM/startup jobs disabled; real auth and PostgreSQL.')
        uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning', access_log=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
