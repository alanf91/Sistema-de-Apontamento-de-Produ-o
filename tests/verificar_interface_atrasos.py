from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP));sys.path.insert(0,str(APP/'tests'))
code='''
import test_atrasos as t
if not hasattr(t,'ui_fixture'):
    t.ui_fixture=t.Atrasos();t.ui_fixture.setUp()
    t.ui_fixture.plano()
    t.ui_fixture.f.fechar(t.ui_fixture.f.abrir(),40,parcial=True)
f=t.ui_fixture.f
f.a.agora_iso=lambda:'2026-10-28 12:00:00'
f.a.inicializar_banco_operacional=lambda:None
f.a.inicializar_catalogo_fichas=lambda:None
f.a.apontamento_autenticado=lambda:True
from j2i_industrial_ui import renderizar
renderizar(f.a,'⏳ Saldo em atraso por equipamento')
'''
a=AppTest.from_string(code,default_timeout=15).run()
assert not a.exception,[x.message for x in a.exception]
assert a.dataframe[0].value.iloc[0]['Total em atraso']==60
assert a.metric[0].value=='1'
a.checkbox(key='atrasos_pendentes').set_value(False).run()
assert not a.exception
assert len(a.dataframe[0].value)==2
a.selectbox(key='atrasos_eq').set_value(2).run()
assert not a.exception
assert a.dataframe[0].value.iloc[0]['Total em atraso']==0
assert a.metric[0].value=='0'
import test_atrasos as t
t.ui_fixture.tearDown()
print('Interface de atrasos OK: rota industrial, saldo parcial, equipamentos sem atraso e filtro individual.')
