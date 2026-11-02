import json
import unittest
from datetime import date
import test_sessoes_parciais as fixture
from j2i_atrasos_equipamento import consultar

class Atrasos(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Fluxo();self.f.setUp()
    def tearDown(self):self.f.tearDown()
    def plano(self,op='00000001',etapa=1,eq=1,dia='2026-10-27',tipo='pecas',medida='2/0.5/0.018',multiplicador=1):
        regra=dict(tipo=tipo,dimensao='m',multiplicador=multiplicador,bordas_c=0,bordas_l=0)
        import j2i_industrial as m
        regra=m.validar_regra(regra)
        with self.f.connect() as c:
            c.execute('INSERT INTO mes_programacao VALUES(?,?,?,?,?,?,?,?,?,?)',(op,etapa,eq,'10','Peca',100,medida,dia,json.dumps(regra),1))
    def consultar(self):
        with self.f.connect() as c:return consultar(c,date(2026,10,28))
    def test_corte_ontem_inclui_nao_iniciadas(self):
        self.plano();self.plano('00000002',dia='2026-10-28')
        r,d,a=self.consultar()
        self.assertEqual(r[0]['Total em atraso'],100)
        self.assertEqual(len(d),1);self.assertEqual(d[0]['Dias em atraso'],1)
        self.assertEqual(r[1]['Total em atraso'],0)
    def test_apontamento_hoje_reduz_saldo_e_total_sai(self):
        self.plano();i=self.f.abrir(dia='2026-10-28 07:00:00')
        self.f.fechar(i,38,2,True,dia='2026-10-28 08:00:00')
        r,d,_=self.consultar();self.assertEqual(r[0]['Total em atraso'],60)
        self.assertIn('Parcial',d[0]['Situação'])
        self.f.fechar(self.f.abrir(dia='2026-10-28 09:00:00'),60,dia='2026-10-28 10:00:00')
        r,d,_=self.consultar();self.assertEqual(d,[]);self.assertEqual(r[0]['Total em atraso'],0)
    def test_reabertura_nao_duplica_saldo(self):
        self.plano();self.f.fechar(self.f.abrir(),40,parcial=True);self.f.abrir()
        r,d,_=self.consultar();self.assertEqual(r[0]['Total em atraso'],60)
        self.assertEqual(d[0]['Situação'],'Em andamento');self.assertEqual(len(d),1)
    def test_metrica_area_linear_e_sucata_anterior(self):
        self.plano(tipo='area',multiplicador=2)
        self.plano(etapa=2,eq=2,tipo='comprimento')
        r,d,_=self.consultar();self.assertEqual([x['Total em atraso'] for x in r],[200,200])
        # Primeira etapa ainda não tinha snapshot; ao abrir utiliza as dimensões da ficha.
        self.f.fechar(self.f.abrir(),90,10)
        r,d,_=self.consultar();self.assertEqual(r[1]['Total em atraso'],180)
        self.assertEqual(d[0]['Saldo em peças'],90)
    def test_passagens_repetidas_mesma_op_contam_trabalho(self):
        self.plano();self.plano(etapa=3)
        r,d,_=self.consultar();self.assertEqual(r[0]['Total em atraso'],200)
        self.assertEqual(r[0]['OPs em atraso'],1);self.assertEqual(r[0]['Passagens pendentes'],2)
    def test_unidades_diferentes_separadas_e_regra_preservada(self):
        self.plano(tipo='area');self.plano('00000002',tipo='comprimento')
        self.f.fechar(self.f.abrir(),40,parcial=True)
        with self.f.connect() as c:
            r=json.loads(c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=1').fetchone()[0])
            r['multiplicador']=10;c.execute('UPDATE mes_metricas SET regra_json=? WHERE equipamento_id=1',(json.dumps(r),))
        rs,_,_=self.consultar();rs=[r for r in rs if r['equipamento_id']==1]
        self.assertEqual({r['Unidade'] for r in rs},{'M²','m linear'})
        self.assertEqual(next(r['Total em atraso'] for r in rs if r['Unidade']=='M²'),60)
    def test_dimensao_invalida_nao_vira_zero(self):
        self.plano(tipo='area',medida='invalida')
        r,d,_=self.consultar();self.assertIsNone(r[0]['Total em atraso'])
        self.assertEqual(r[0]['Pendências de cálculo'],1);self.assertTrue(d[0]['Pendência'])
    def test_zero_ignorado_mantem_contagem_e_soma_valida(self):
        self.plano(tipo='area',medida='0/0/0')
        self.plano('00000002',tipo='area')
        r,d,_=self.consultar()
        self.assertEqual(r[0]['Total em atraso'],100)
        self.assertEqual(r[0]['Passagens ignoradas (zero)'],1)
        self.assertEqual(r[0]['Passagens pendentes'],2)
        self.assertEqual(r[0]['OPs em atraso'],2)
        self.assertEqual(r[0]['Pendências de cálculo'],0)
        self.assertIsNone(d[0]['Saldo na métrica'])
    def test_somente_zero_nao_altera_medidas(self):
        self.plano(tipo='area',medida='0/0/0')
        r,d,_=self.consultar()
        self.assertEqual(r[0]['Total em atraso'],0)
        self.assertEqual(r[0]['Passagens ignoradas (zero)'],1)
        with self.f.connect() as c:
            self.assertEqual(c.execute('SELECT medida FROM mes_programacao').fetchone()[0],'0/0/0')

    def test_data_invalida_e_sem_plano_geram_aviso(self):
        self.plano(dia='');self.f.abrir(op='00000002')
        r,d,a=self.consultar();self.assertEqual(d,[]);self.assertEqual(len(a),2)
    def test_inativo_com_atraso_fica_oculto(self):
        self.plano()
        with self.f.connect() as c:c.execute('UPDATE equipamentos SET ativo=0 WHERE id=1')
        r,d,_=self.consultar();self.assertNotIn(1,{x['equipamento_id'] for x in r});self.assertFalse(d)
        with self.f.connect() as c:c.execute('UPDATE equipamentos SET ativo=1 WHERE id=1')
        r,_,_=self.consultar();self.assertEqual(r[0]['Total em atraso'],100)
    def test_saldo_iniciado_congelado_em_sequencia_livre(self):
        self.plano(etapa=2,eq=2)
        with self.f.connect() as c:c.execute("INSERT INTO mes_opcoes VALUES('sequencia_livre_lote:10','1')")
        self.f.fechar(self.f.abrir(eq=2),40,parcial=True,eq=2)
        self.f.fechar(self.f.abrir(),90,10)
        r,d,_=self.consultar();self.assertEqual(d[0]['Saldo em peças'],60)

if __name__=='__main__':unittest.main()
