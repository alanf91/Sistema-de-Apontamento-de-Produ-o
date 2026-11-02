from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP));sys.path.insert(0,str(APP/'tests'))
code='''
import test_correcao_coladeiras as t
import json
from datetime import date
if not hasattr(t,'ui_fixture'):
    t.ui_fixture=t.ReaplicacaoPorPassagem();t.ui_fixture.setUp()
    with t.ui_fixture.f.connect() as c:
        regra=t.m.validar_regra(dict(tipo='comprimento',dimensao='m',multiplicador=1))
        regra['permitir_dimensao_zero']=True
        c.execute("UPDATE mes_programacao SET data_programada=?,medida='0,000/0,000/0,000',regra_json=? WHERE etapa=1",(date.today().isoformat(),json.dumps(regra)))
from j2i_programacao_diaria import renderizar
renderizar(t.ui_fixture.a)
'''
a=AppTest.from_string(code,default_timeout=15).run()
assert not a.exception,[x.message for x in a.exception]
assert any('OPs com dimensão pendente' in e.label for e in a.expander)
frames=[d.value for d in a.dataframe]
pend=next(d for d in frames if 'Medida cadastrada' in d.columns)
assert pend.iloc[0]['OP']=='00000001' and pend.iloc[0]['Medida cadastrada']=='0,000/0,000/0,000'
import test_correcao_coladeiras as t
t.ui_fixture.tearDown()
print('Interface OK: lista de OPs/etapas com dimensão pendente visível na programação diária.')
