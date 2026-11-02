from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP));sys.path.insert(0,str(APP/'tests'))
code='''
import test_encerramento_ppcp as t
if not hasattr(t,'ui_fixture'):
    t.ui_fixture=t.Encerramento();t.ui_fixture.setUp();t.ui_fixture.plano();t.ui_fixture.plano(op="00000002")
from j2i_atrasos_equipamento import renderizar
renderizar(t.ui_fixture.f.a)
'''
a=AppTest.from_string(code,default_timeout=15).run()
assert not a.exception
a.selectbox(key='atrasos_eq').set_value(1).run()
a.button(key='preparar_1').click().run()
assert not a.exception
a.radio[0].set_value('Somente as passagens marcadas').run()
assert next(x for x in a.button if x.label=='Encerrar somente as passagens marcadas').disabled
keys=['selecao_ppcp_1_'+a.session_state['ppcp_previa_1'][1]]
a.session_state[keys[0]]={'edited_rows':{0:{'Encerrar':True}},'added_rows':[],'deleted_rows':[]}
a.run()
a.text_area[0].set_value('Encerramento administrativo de teste')
confirm=next(x for x in a.checkbox if x.label.startswith('Conferi'))
confirm.check()
next(x for x in a.button if x.label=='Encerrar somente as passagens marcadas').click().run()
assert not a.exception,[x.message for x in a.exception]
assert any('encerradas manualmente' in x.value for x in a.success)
assert a.metric[2].value=='1'
import test_encerramento_ppcp as t
with t.ui_fixture.f.connect() as c:
    assert c.execute('SELECT COUNT(*) FROM mes_encerramentos_ppcp').fetchone()[0]==1
t.ui_fixture.tearDown()
print('Interface de seleção: seleção, prévia, motivo, confirmação, histórico e saldo atualizado OK.')
