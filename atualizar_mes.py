"""Atualizador conservador: nunca copia os bancos/Excel do pacote sobre o servidor."""
import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def atualizar(origem, destino):
    origem, destino = Path(origem).resolve(), Path(destino).resolve()
    if origem == destino or not (destino/'J2I_MES.py').is_file():
        raise ValueError('Use uma pasta de origem separada e informe a pasta atual que contém J2I_MES.py.')
    nomes = ['LEIA_ME_SELECAO_PPCP.md','j2i_encerramento_ppcp.py','LEIA_ME_ENCERRAR_ATRASOS.md','LEIA_ME_ATIVOS_DESEMPENHO.md','LEIA_ME_TODOS_EQUIPAMENTOS.md','LEIA_ME_AJUSTE_ATRASOS.md','J2I_MES.py','j2i_industrial.py','j2i_industrial_ui.py','j2i_importacao_v6.py',
             'j2i_capacidade_sequenciamento.py','j2i_sequencia_producao.py','j2i_equipamentos_ativos.py','j2i_paradas_consulta.py','j2i_estatistica.py','j2i_sessoes.py','j2i_operacao_multipla.py','j2i_jornadas.py','j2i_tempos_operacao.py','j2i_calendario_producao.py',
             'j2i_estoque_lote.py','j2i_estoque_total.py','j2i_programacao_diaria.py',
             'corrigir_coladeira_122.py','LEIA_ME_COLADEIRAS.md','j2i_desempenho_periodo.py','LEIA_ME_DESEMPENHO.md','j2i_atrasos_equipamento.py','LEIA_ME_ATRASOS.md','j2i_sessoes_producao.py','j2i_parciais.py','j2i_cadastros.py','j2i_excel_lock.py','j2i_consumo_insumos.py','j2i_pdf_industrial.py','j2i_pdf_lotes.py','j2i_sequenciamento.py','j2i_telas_operacao.py',
             'requirements.txt','LEIA_ME_PARCIAIS.md','LEIA_ME_V6.md','INICIAR_MES_V6.bat','alimentador_industrial.py']
    for nome in nomes:
        if not (origem/nome).is_file():raise ValueError('Pacote incompleto: '+nome)
    backup = destino/'backups'/('antes_mes_encerrar_atrasos_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    for nome in nomes:
        if (destino/nome).exists():shutil.copy2(destino/nome,backup/nome)
    # Bancos locais são copiados pela API SQLite, incluindo alterações do WAL.
    for nome in ['apontamentos_operacionais.db','catalogo_fichas.db']:
        p=destino/nome
        if p.exists():
            with sqlite3.connect(p) as src, sqlite3.connect(backup/nome) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup inválido: '+nome)
    if (destino/'PPCP_ACOMPAN.xlsx').exists():shutil.copy2(destino/'PPCP_ACOMPAN.xlsx',backup/'PPCP_ACOMPAN.xlsx')
    instalados=[]
    try:
        for nome in nomes:
            temp=destino/(nome+'.novo')
            shutil.copy2(origem/nome,temp)
            temp.replace(destino/nome)
            instalados.append(nome)
    except Exception:
        for nome in instalados:
            if (backup/nome).exists():shutil.copy2(backup/nome,destino/nome)
            else:(destino/nome).unlink(missing_ok=True)
        raise
    return backup


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destino',required=True,help='Pasta atual do aplicativo no servidor')
    p.add_argument('--servidor-parado',action='store_true',help='Confirma que Streamlit e alimentadores foram encerrados')
    args=p.parse_args()
    if not args.servidor_parado:p.error('Encerre o MES e alimentadores e use --servidor-parado. O script não interrompe serviços automaticamente.')
    backup=atualizar(Path(__file__).resolve().parent,args.destino)
    print('Código atualizado. Bancos e planilhas existentes preservados.')
    print('Backup:',backup)
    print('Na pasta de destino, execute: python -m pip install -r requirements.txt')
    print('Depois reinicie o MES pelo comando habitual.')


if __name__=='__main__':main()
