"""Teste de interface com Streamlit AppTest; execute separadamente dos testes unitários."""
from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP));sys.path.insert(0,str(APP/'tests'))
code='''
import test_sessoes_parciais as t
import j2i_sessoes
if not hasattr(t, 'ui_fixture'):
    t.ui_fixture=t.Fluxo();t.ui_fixture.setUp()
    t.ui_fixture.abrir(op='00000001');t.ui_fixture.abrir(op='00000002')
f=t.ui_fixture
a=f.a
a.obter_equipamento_sessao=lambda:f.eq[1]
a.MOTIVOS_PARADA_PADRONIZADOS={'Outras':['Manutenção']}
a.normalizar_lote=lambda x:str(x).strip()
j2i_sessoes.manter=lambda a,eq:None
from j2i_telas_operacao import operacao
operacao(a)
'''
a=AppTest.from_string(code,default_timeout=15).run()
def ok():
    assert not a.exception, [e.message for e in a.exception]
def button(label):return next(b for b in a.button if b.label==label)
ok()
button('Finalizar OP').click().run();ok()
a.radio(key='op_modo_1').set_value('Parcial').run();ok()
a.number_input(key='op_processado_1').set_value(40).run();ok()
button('Confirmar encerramento').click().run();ok()
import test_sessoes_parciais as t
assert t.ui_fixture.rows()[0]['encerramento_parcial']==1
next(x for x in a.text_area if x.label=='OPs para iniciar').set_value('00000001')
button('Iniciar todas as OPs informadas').click().run();ok()
assert t.ui_fixture.rows()[-1]['quantidade_programada']==60
for i,modo in [(2,'Total'),(3,'Parcial')]:
    a.checkbox(key=f'multi_1_{i}_selecionar').set_value(True)
    a.radio(key=f'multi_1_{i}_modo').set_value(modo)
a.number_input(key='multi_1_3_qtd').set_value(20)
button('Confirmar encerramento das OPs selecionadas').click().run();ok()
rs=t.ui_fixture.rows()
assert [r['encerramento_parcial'] for r in rs]==[1,0,1]
assert rs[-1]['quantidade_boa']==20
next(x for x in a.text_input if x.label=='Leia o código de barras da OP').set_value('00000001')
button('Iniciar OP').click().run();ok()
assert t.ui_fixture.rows()[-1]['quantidade_programada']==40
print('Interface OK: parcial individual, reabertura em lote, lote misto e reabertura individual com saldo 40.')
t.ui_fixture.tearDown()
