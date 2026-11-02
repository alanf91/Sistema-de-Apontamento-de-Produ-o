from pathlib import Path
from datetime import date
import sys
from streamlit.testing.v1 import AppTest
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP));sys.path.insert(0,str(APP/'tests'))
code='''
import test_desempenho_periodo as t
if not hasattr(t,'ui_fixture'):
    t.ui_fixture=t.Desempenho();t.ui_fixture.setUp()
    f=t.ui_fixture.f
    f.fechar(f.abrir(),40,parcial=True)
    f.fechar(f.abrir(dia='2026-10-28 08:00:00'),60,dia='2026-10-28 09:00:00')
    f.fechar(f.abrir(eq=2),100,eq=2)
    with f.connect() as c:c.execute('UPDATE equipamentos SET ativo=0 WHERE id=2')
f=t.ui_fixture.f
f.a.agora_iso=lambda:'2026-10-27 12:00:00'
f.a.inicializar_banco_operacional=lambda:None
f.a.inicializar_catalogo_fichas=lambda:None
f.a.apontamento_autenticado=lambda:True
from j2i_industrial_ui import renderizar
renderizar(f.a,'📊 Desempenho Industrial')
'''
a=AppTest.from_string(code,default_timeout=15).run()
def check():assert not a.exception,[x.message for x in a.exception]
check();df=a.dataframe[0].value
assert len(df)==2 and df['Programado'].sum()==0
assert df['Realizado total'].sum()==140
a.date_input(key='desempenho_ate').set_value(date(2026,10,28)).run();check()
assert a.dataframe[0].value['Realizado total'].sum()==200
a.selectbox(key='desempenho_eq').set_value(2).run();check()
assert len(a.dataframe[0].value)==1 and a.dataframe[0].value.iloc[0]['Cadastro']=='Inativo'
a.date_input(key='desempenho_de').set_value(date(2026,10,29)).run();check()
assert any('Período inválido' in x.value for x in a.error)
import test_desempenho_periodo as t
t.ui_fixture.tearDown()
print('Interface OK: um dia, intervalo, equipamentos inativos, filtro individual e datas inválidas.')
