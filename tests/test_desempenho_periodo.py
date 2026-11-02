import unittest,json
from datetime import date
import test_sessoes_parciais as fixture
from j2i_desempenho_periodo import consultar

class Desempenho(unittest.TestCase):
    def setUp(self):self.f=fixture.Fluxo();self.f.setUp()
    def tearDown(self):self.f.tearDown()
    def plano(self,op='00000001',dia='2026-10-27'):
        with self.f.connect() as c:
            regra=c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=1').fetchone()[0]
            c.execute('INSERT INTO mes_programacao VALUES(?,?,?,?,?,?,?,?,?,?)',(op,1,1,'10','Peca',100,'1/1/0.018',dia,regra,1))
    def consultar(self,de=date(2026,10,27),ate=date(2026,10,27),ids=None):
        with self.f.connect() as c:return consultar(c,de,ate,ids)
    def test_sem_programacao_exibe_total_com_sucata_sem_duplicar_retrabalho(self):
        self.f.fechar(self.f.abrir(),90,10,rt=5)
        r,p,d,a=self.consultar()
        self.assertEqual(r[0]['Programado'],0);self.assertEqual(r[0]['Realizado total'],100)
        self.assertEqual(r[0]['Realizado bom'],90);self.assertEqual(r[0]['Retrabalho'],5)
        self.assertIsNone(r[0]['Atingimento bom/programado (%)']);self.assertFalse(p)
    def test_inativo_com_apontamento_oculto_e_reativacao(self):
        self.f.fechar(self.f.abrir(),100)
        with self.f.connect() as c:c.execute('UPDATE equipamentos SET ativo=0 WHERE id=1')
        r,_,d,_=self.consultar();self.assertNotIn(1,{x['equipamento_id'] for x in r});self.assertFalse(d)
        self.assertEqual(self.consultar(ids=[1])[0],[])
        with self.f.connect() as c:c.execute('UPDATE equipamentos SET ativo=1 WHERE id=1')
        r,_,_,_=self.consultar();self.assertEqual(r[0]['Realizado total'],100)
    def test_programacao_fora_do_periodo_nao_vira_programado(self):
        self.plano(dia='2026-10-26');self.f.fechar(self.f.abrir(),100)
        r,_,_,_=self.consultar();self.assertEqual(r[0]['Programado'],0)
    def test_multiplos_dias_parciais_e_limite_final(self):
        self.f.fechar(self.f.abrir(),40,parcial=True)
        self.f.fechar(self.f.abrir(dia='2026-10-28 08:00:00'),60,dia='2026-10-28 23:59:59')
        self.f.fechar(self.f.abrir(op='00000002',dia='2026-10-29 00:00:00'),100,dia='2026-10-29 00:00:00')
        r,_,d,_=self.consultar(ate=date(2026,10,28));self.assertEqual(r[0]['Realizado total'],100);self.assertEqual(len(d),2)
        r,_,_,_=self.consultar();self.assertEqual(r[0]['Realizado total'],40)
    def test_programado_sem_realizado_e_equipamento_sem_atividade(self):
        self.plano()
        r,_,_,_=self.consultar();self.assertEqual(len(r),2);self.assertEqual(r[0]['Programado'],100);self.assertEqual(r[0]['Realizado total'],0)
        self.assertEqual(self.consultar(ids=[2])[0][0]['Programado'],0)
        self.assertEqual(self.consultar(ids=[2])[0][0]['Realizado total'],0)
    def test_mais_equipamentos_sem_programacao(self):
        self.f.fechar(self.f.abrir(),100)
        self.f.fechar(self.f.abrir(eq=2),100,eq=2)
        r,_,_,_=self.consultar();self.assertEqual(len(r),2)
        self.assertTrue(all(x['Programado']==0 and x['Realizado total']==100 for x in r))
        self.assertEqual(len(self.consultar(ids=[2])[0]),1)
    def test_legado_sem_snapshot_converte_e_avisa(self):
        i=self.f.abrir();self.f.fechar(i,100)
        with self.f.connect() as c:
            c.execute('DELETE FROM mes_resultados WHERE ordem_id=?',(i,))
            regra=dict(tipo='comprimento',dimensao='m',multiplicador=2,bordas_c=0,bordas_l=0)
            c.execute('UPDATE mes_metricas SET regra_json=? WHERE equipamento_id=1',(json.dumps(regra),))
        r,_,d,a=self.consultar();self.assertEqual(r[0]['Realizado total'],200)
        self.assertTrue(a);self.assertIn('cadastro atual',d[0]['Origem da métrica'])
    def test_legado_sem_regra_aparece_em_pecas_com_aviso(self):
        i=self.f.abrir();self.f.fechar(i,100)
        with self.f.connect() as c:c.execute('DELETE FROM mes_resultados');c.execute('DELETE FROM mes_metricas')
        r,_,_,a=self.consultar();self.assertEqual(r[0]['Realizado total'],100)
        self.assertEqual(r[0]['Unidade'],'peças (conversão pendente)');self.assertTrue(a)
    def test_unidades_separadas_e_snapshot_preservado(self):
        self.f.fechar(self.f.abrir(),100)
        with self.f.connect() as c:
            regra=dict(tipo='area',dimensao='m',multiplicador=2,bordas_c=0,bordas_l=0)
            c.execute('UPDATE mes_metricas SET regra_json=? WHERE equipamento_id=1',(json.dumps(regra),))
        self.f.fechar(self.f.abrir(op='00000002'),100)
        r,_,_,_=self.consultar(ids=[1]);self.assertEqual(len(r),2)
        self.assertEqual({x['Unidade']:x['Realizado total'] for x in r},{'uni':100,'M²':200})
    def test_sem_programacao_nem_apontamento_em_varios_dias(self):
        r,p,d,a=self.consultar(ate=date(2026,10,28))
        self.assertEqual(len(r),2)
        self.assertTrue(all(x['Programado']==0 and x['Realizado total']==0 for x in r))
        self.assertFalse(p);self.assertFalse(d)
        self.assertTrue(all(x['Atingimento bom/programado (%)'] is None for x in r))
    def test_filtro_equipamento_e_metrica_ausente(self):
        with self.f.connect() as c:c.execute('DELETE FROM mes_metricas WHERE equipamento_id=2')
        r,_,_,_=self.consultar(ids=[2])
        self.assertEqual(len(r),1);self.assertEqual(r[0]['equipamento_id'],2)
        self.assertEqual(r[0]['Unidade'],'Métrica não configurada')
        self.assertEqual(self.consultar(ids=[])[0],[])

    def test_intervalo_invalido(self):
        with self.assertRaises(ValueError):self.consultar(de=date(2026,10,28))

if __name__=='__main__':unittest.main()
