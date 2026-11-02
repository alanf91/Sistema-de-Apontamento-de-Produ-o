"""Apontamentos manuais incrementais na mesma transação do arquivo Excel."""
from pathlib import Path
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from openpyxl import load_workbook
from j2i_excel_lock import excel_lock

ABA_HISTORICO = '7_APONTAMENTOS_MANUAIS'
COLUNA_ID = 'J2I_ID_APONTAMENTO'
CAMPOS = ['Evento', 'Requisição', 'Registrado em', 'Data produção', 'Usuário', 'ID linha', 'Aba origem', 'Linha Excel', 'OP/Lote', 'Código Peça', 'Descrição Peça', 'Setor', 'Máquina/Posto', 'Tipo', 'Quantidade lançada', 'Total anterior', 'Total apontado', 'Qtde programada', 'Saldo']
CHAVES = ['lote', 'codigo', 'descricao', 'setor', 'maquina', 'operacao', 'qtde_programada', 'qtde_realizada', 'data_realizada', 'id_manual']


def numero(valor):
    if valor is None or str(valor).strip() == '':
        return Decimal(0)
    try:
        resultado = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError(f'Quantidade inválida: {valor}. Revise a linha na planilha.') from None
    if not resultado.is_finite() or resultado < 0:
        raise ValueError('Quantidades devem ser finitas e não negativas.')
    return resultado


def assinatura(valores):
    return hashlib.sha256(json.dumps([str(v) if v is not None else '' for v in valores], ensure_ascii=False).encode()).hexdigest()


def assinatura_linha(valores, colunas):
    return assinatura([valores[colunas[k]-1] if k in colunas and colunas[k] <= len(valores) else None for k in CHAVES])


def salvar(a, caminho, nome_aba, lancamentos, data_producao, requisicao, usuario='pcp', criar_backup=False):
    """Revalida sob lock; rejeita lote inteiro se uma linha estiver desatualizada."""
    caminho = Path(caminho).resolve()
    if not lancamentos or not requisicao:
        raise ValueError('Nenhum apontamento informado.')
    if len({int(l['linha']) for l in lancamentos}) != len(lancamentos):
        raise ValueError('Uma linha não pode aparecer duas vezes no mesmo envio.')
    with excel_lock(caminho):
        wb = load_workbook(caminho, data_only=False)
        temporario = None
        try:
            if ABA_HISTORICO in wb.sheetnames:
                historico = wb[ABA_HISTORICO]
                if [c.value for c in historico[1]] != CAMPOS:
                    raise ValueError('A aba de histórico tem estrutura diferente. Nenhuma alteração realizada.')
                if any(r[0] == requisicao for r in historico.iter_rows(min_row=2, min_col=2, max_col=2, values_only=True)):
                    return {'linhas': 0, 'duplicado': True, 'backup': None}
            else:
                historico = wb.create_sheet(ABA_HISTORICO)
                historico.append(CAMPOS)
                historico.freeze_panes = 'A2'
            ws = wb[nome_aba]
            col = a.localizar_colunas(ws)
            with_values = load_workbook(caminho, read_only=True, data_only=True)
            try:
                leitura = with_values[nome_aba]
                solicitadas = {int(l['linha']) for l in lancamentos}
                atuais = {i: valores for i,valores in enumerate(leitura.iter_rows(values_only=True), 1) if i in solicitadas}
            finally:
                with_values.close()
            preparo = []
            for item in lancamentos:
                linha = int(item['linha'])
                valores = atuais.get(linha)
                if linha < 2 or valores is None or assinatura_linha(valores, col) != item['assinatura']:
                    raise ValueError(f'Linha {linha} foi alterada por outro usuário ou pelo alimentador. Atualize a página antes de salvar.')
                def valor(chave):
                    return valores[col[chave]-1] if chave in col else None
                programada = numero(valor('qtde_programada'))
                anterior = numero(valor('qtde_realizada'))
                if programada <= 0:
                    raise ValueError(f'Linha {linha}: quantidade programada deve ser maior que zero.')
                saldo = programada - anterior
                if saldo <= 0:
                    raise ValueError(f'Linha {linha}: não há saldo para apontar.')
                quantidade = saldo if item['completo'] else numero(item['quantidade'])
                if quantidade <= 0 or quantidade > saldo:
                    raise ValueError(f'Linha {linha}: informe quantidade maior que zero e no máximo {saldo} (saldo atual).')
                if item['completo'] and numero(item.get('quantidade', 0)) != 0:
                    raise ValueError(f'Linha {linha}: escolha a caixinha ou o apontamento parcial, sem preencher os dois.')
                preparo.append((linha, valores, programada, anterior, quantidade, anterior+quantidade))
            cabecalhos = {c.value: c.column for c in ws[1]}
            id_col = cabecalhos.get(COLUNA_ID)
            if id_col is None:
                id_col = ws.max_column+1
                ws.cell(1,id_col,COLUNA_ID)
                from openpyxl.utils import get_column_letter
                ws.column_dimensions[get_column_letter(id_col)].hidden = True
            eventos_existentes = {}
            for r in historico.iter_rows(min_row=2, values_only=True):
                eventos_existentes.setdefault(str(r[5]), []).append(r)
            agora = datetime.now()
            data_excel = datetime.combine(data_producao, time.min)
            for linha, valores, programada, anterior, quantidade, total in preparo:
                identificador = ws.cell(linha,id_col).value or str(uuid.uuid4())
                anteriores = eventos_existentes.get(str(identificador), [])
                if anteriores:
                    if numero(anteriores[0][15]) != 0 or numero(anteriores[-1][16]) != anterior:
                        raise ValueError(f'Linha {linha}: histórico anterior incompleto ou divergente. Regularize antes de novos apontamentos.')
                elif anterior > 0:
                    data_legado = a.valor_para_data(valores[col['data_realizada']-1])
                    if data_legado is None:
                        raise ValueError(f'Linha {linha}: saldo anterior sem data. Informe a data real do lançamento anterior antes de continuar.')
                    def original(chave):
                        return valores[col[chave]-1] if chave in col else ''
                    historico.append([str(uuid.uuid4()), requisicao, agora, datetime.combine(data_legado,time.min), usuario, identificador, nome_aba, linha,
                        original('lote'), original('codigo'), original('descricao'), original('setor'), original('maquina'),
                        'Saldo anterior', float(anterior), 0.0, float(anterior), float(programada), float(programada-anterior)])
                    historico.cell(historico.max_row,3).number_format='dd/mm/yyyy hh:mm:ss'
                    historico.cell(historico.max_row,4).number_format='dd/mm/yyyy'
                ws.cell(linha,id_col,identificador)
                ws.cell(linha,col['qtde_realizada'],float(total)).number_format = '0.##'
                # A coluna legada contém a data mais recente; o histórico preserva cada dia.
                data_anterior = a.valor_para_data(valores[col['data_realizada']-1])
                ultima = max(data_producao, data_anterior) if data_anterior else data_producao
                ws.cell(linha,col['data_realizada'],datetime.combine(ultima,time.min)).number_format = 'dd/mm/yyyy'
                if 'status' in col:
                    ws.cell(linha,col['status'],'Concluído' if total == programada else 'Em produção')
                if 'percentual' in col:
                    ws.cell(linha,col['percentual'],float(total/programada)).number_format = '0%'
                def dado(chave):
                    return valores[col[chave]-1] if chave in col else ''
                historico.append([str(uuid.uuid4()), requisicao, agora, data_excel, usuario, identificador, nome_aba, linha,
                    dado('lote'), dado('codigo'), dado('descricao'), dado('setor'), dado('maquina'),
                    'Conclusão' if total == programada else 'Parcial', float(quantidade),float(anterior),float(total),float(programada),float(programada-total)])
                historico.cell(historico.max_row,3).number_format='dd/mm/yyyy hh:mm:ss'
                historico.cell(historico.max_row,4).number_format='dd/mm/yyyy'
            historico.auto_filter.ref=historico.dimensions
            backup = None
            if criar_backup:
                backup=caminho.with_name(f'{caminho.stem}_backup_{agora:%Y%m%d_%H%M%S_%f}{caminho.suffix}')
                shutil.copy2(caminho, backup)
            # Salvar em arquivo temporário evita deixar o XLSX pela metade em uma falha.
            handle, temporario = tempfile.mkstemp(prefix='.j2i_parcial_',suffix='.xlsx',dir=caminho.parent)
            os.close(handle)
            if wb.calculation is not None:
                wb.calculation.fullCalcOnLoad = True
                wb.calculation.forceFullCalc = True
            wb.save(temporario)
            wb.close()
            os.replace(temporario,caminho)
            temporario=None
            return {'linhas':len(preparo),'duplicado':False,'backup':backup}
        finally:
            wb.close()
            if temporario and os.path.exists(temporario):
                os.unlink(temporario)


def historico(caminho):
    wb=load_workbook(caminho,read_only=True,data_only=True)
    try:
        if ABA_HISTORICO not in wb.sheetnames:
            return []
        return [dict(zip(CAMPOS,r)) for r in wb[ABA_HISTORICO].iter_rows(min_row=2,values_only=True)]
    finally:
        wb.close()
