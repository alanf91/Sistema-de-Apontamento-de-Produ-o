import json
import unittest
from datetime import date
import test_sessoes_parciais as fixture
from j2i_encerramento_ppcp import previa,encerrar
from j2i_atrasos_equipamento import consultar
from j2i_desempenho_periodo import consultar as desempenho
from j2i_telas_operacao import consultar_ops_pendentes


class Encerramento(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Fluxo();self.f.setUp()
        self.f.a.apontamento_autenticado=lambda:True
        self.f.a.LOGIN_APONTAMENTO='ppcp_teste'
        self.f.a.agora_iso=lambda:'2026-10-28 15:00:00'
    def tearDown(self):self.f.tearDown()
    def plano(self,op='00000001',etapa=1,eq=1,dia='2026-10-27'):
        with self.f.connect() as c:
            regra=c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=?',(eq,)).fetchone()[0]
            c.execute('INSERT INTO mes_programacao VALUES(?,?,?,?,?,?,?,?,?,?)',(op,etapa,eq,'10','Peça',100,'1/1/0.018',dia,regra,1))
    def assinatura(self):
        with self.f.connect() as c:return previa(c,1,date(2026,10,28))[1]
    def fechar(self):return encerrar(self.f.a,1,self.assinatura(),'Limpeza de carteira PPCP')
    def test_nao_iniciada_escopo_auditoria_e_reabertura(self):
        self.plano();self.plano(etapa=2,eq=2);self.plano(etapa=3,dia='2026-10-28')
        self.assertEqual(self.fechar(),1)
        with self.f.connect() as c:
            m=dict(c.execute('SELECT * FROM mes_encerramentos_ppcp').fetchone())
            self.assertEqual(m['usuario'],'ppcp_teste');self.assertEqual(m['corte'],'2026-10-27')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM ordens_operacionais').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mes_resultados').fetchone()[0],0)
            _,d,_=consultar(c,date(2026,10,28));self.assertEqual([x['Passagem'] for x in d],[2])
            self.assertNotIn(1,[x['Passagem'] for x in consultar_ops_pendentes(c,1,'10')])
        with self.assertRaises(ValueError):self.f.abrir()
        with self.assertRaises(ValueError):self.f.abrir(eq=2)
    def test_aberta_nao_gera_producao_estoque_ou_tempo(self):
        self.plano();self.f.estoque();i=self.f.abrir()
        with self.f.connect() as c:
            antes=[tuple(r) for r in c.execute('SELECT * FROM mes_resultados')]
        self.fechar()
        r=self.f.rows()[0];self.assertEqual(r['status'],'ENCERRADA_PPCP')
        self.assertEqual(r['duracao_segundos'],0);self.assertEqual(r['quantidade_boa'],0)
        self.assertEqual(self.f.saldo(),1000)
        with self.f.connect() as c:
            self.assertEqual(antes,[tuple(r) for r in c.execute('SELECT * FROM mes_resultados')])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mes_movimentos').fetchone()[0],0)
            rs,_,ds,_=desempenho(c,date(2026,10,27),date(2026,10,28))
            self.assertFalse(ds);self.assertTrue(all(x['Realizado total']==0 for x in rs))
        with self.assertRaises(ValueError):self.f.fechar(i,100)
    def test_parcial_preserva_realizado_e_estoque(self):
        self.plano();self.f.estoque();self.f.fechar(self.f.abrir(),40,parcial=True)
        saldo=self.f.saldo();self.f.abrir(dia='2026-10-28 08:00:00')
        self.fechar();self.assertEqual(self.f.saldo(),saldo)
        with self.f.connect() as c:
            r,_,d,_=desempenho(c,date(2026,10,27),date(2026,10,28),[1])
            self.assertEqual(r[0]['Realizado total'],40);self.assertEqual(len(d),1)
            self.assertEqual(consultar(c,date(2026,10,28))[1],[])
    def test_previa_obsoleta_e_duplo_clique(self):
        self.plano();sig=self.assinatura();self.f.abrir()
        with self.assertRaisesRegex(ValueError,'mudaram'):encerrar(self.f.a,1,sig,'Motivo')
        sig=self.assinatura();encerrar(self.f.a,1,sig,'Motivo')
        with self.assertRaises(ValueError):encerrar(self.f.a,1,sig,'Motivo')
        with self.f.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mes_encerramentos_ppcp').fetchone()[0],1)
    def test_autenticacao_motivo_e_inativo(self):
        self.plano();sig=self.assinatura()
        self.f.a.apontamento_autenticado=lambda:False
        with self.assertRaises(PermissionError):encerrar(self.f.a,1,sig,'Motivo')
        self.f.a.apontamento_autenticado=lambda:True
        with self.assertRaises(ValueError):encerrar(self.f.a,1,sig,' ')
        with self.f.connect() as c:c.execute('UPDATE equipamentos SET ativo=0 WHERE id=1')
        with self.assertRaises(ValueError):encerrar(self.f.a,1,sig,'Motivo')
    def test_lote_inteiro_e_concluida_preservada(self):
        self.plano();self.plano(op='00000002');self.f.fechar(self.f.abrir(),100)
        self.assertEqual(self.fechar(),1)
        with self.f.connect() as c:self.assertEqual(c.execute('SELECT op FROM mes_encerramentos_ppcp').fetchone()[0],'00000002')
    def test_transacao_reverte_todos_em_falha(self):
        self.plano();self.plano(op='00000002');self.f.abrir()
        with self.f.connect() as c:
            c.execute("CREATE TRIGGER falhar BEFORE INSERT ON mes_encerramentos_ppcp WHEN NEW.op='00000002' BEGIN SELECT RAISE(ABORT,'falha simulada'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):self.fechar()
        self.assertEqual(self.f.rows()[0]['status'],'ABERTA')
        with self.f.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mes_encerramentos_ppcp').fetchone()[0],0)
    def test_selecao_preserva_nao_marcadas_e_audita(self):
        self.plano();self.plano(op='00000002');self.plano(etapa=3)
        n=encerrar(self.f.a,1,self.assinatura(),'Somente uma',selecionadas=[('00000001','10',1)])
        self.assertEqual(n,1)
        with self.f.connect() as c:
            _,d,_=consultar(c,date(2026,10,28))
            self.assertEqual({(r['OP'],r['Passagem']) for r in d},{('00000002',1),('00000001',3)})
            audit=json.loads(c.execute("SELECT dados_json FROM mes_auditoria WHERE evento='encerramento_manual_atrasos_ppcp'").fetchone()[0])
            self.assertEqual(audit['modo'],'Selecionadas');self.assertEqual(len(audit['passagens']),1)
    def test_selecao_vazia_ou_fora_do_escopo_nao_encerra(self):
        self.plano();sig=self.assinatura()
        for alvos in ([],[('00000002','10',1)],[('00000001','99',1)]):
            with self.assertRaises(ValueError):encerrar(self.f.a,1,sig,'Motivo',selecionadas=alvos)
        with self.f.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mes_encerramentos_ppcp').fetchone()[0],0)

    def test_reativacao_ou_reprogramacao_nao_reabre(self):
        self.plano();self.fechar()
        with self.f.connect() as c:
            c.execute("UPDATE mes_programacao SET data_programada='2026-10-26'")
            self.assertFalse(consultar(c,date(2026,10,28))[1])
        with self.assertRaises(ValueError):self.f.abrir()


if __name__=='__main__':unittest.main()
