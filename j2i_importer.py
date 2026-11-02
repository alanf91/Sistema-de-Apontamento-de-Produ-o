"""Importação incremental sem sobrescrever apontamentos nem substituir a planilha completa recebida."""
from pathlib import Path
from datetime import datetime
import copy
import os
import shutil
import tempfile
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from j2i_excel_lock import excel_lock

ABA = '5_ACOMPANHAMENTO'
FORMULAS = [11,12,13,18,20,22,23,24,25,26,27,28,29,30]
COLS = ('data_programada','op_lote','cliente_pedido','produto_equipamento',
        'codigo_peca','descricao_peca','operacao','setor','maquina_posto','qtde_programada')

def normal(v):
    return ' '.join(str(v if v is not None else '').split()).upper()

def chave(v):
    return tuple(normal(v.get(c)) for c in ('op_lote','produto_equipamento','codigo_peca','descricao_peca'))

def last_row(ws):
    for row in range(ws.max_row,1,-1):
        if any(ws.cell(row,i).value not in (None,'') for i in (2,5,6,10)):
            return row
    return 1

def model_formula(ws):
    for row in range(2, min(ws.max_row,200)+1):
        if sum(bool(isinstance(ws.cell(row,c).value,str) and ws.cell(row,c).value.startswith('=')) for c in FORMULAS) >= 5:
            return row
    return max(2,last_row(ws))

def copy_row(ws, style_row, formula_row, dst):
    ws.row_dimensions[dst].height = ws.row_dimensions[style_row].height
    for col in range(1,ws.max_column+1):
        a=ws.cell(style_row,col); b=ws.cell(dst,col)
        if a.has_style: b._style=copy.copy(a._style)
        f=ws.cell(formula_row,col)
        if isinstance(f.value,str) and f.value.startswith('='):
            try: b.value=Translator(f.value, origin=f.coordinate).translate_formula(b.coordinate)
            except Exception: b.value=f.value

def importar(planilha, registros, pasta_backup):
    planilha=Path(planilha).resolve(); pasta_backup=Path(pasta_backup).resolve()
    if not planilha.is_file(): raise FileNotFoundError(f'Planilha ausente: {planilha}')
    with excel_lock(planilha):
        wb=load_workbook(planilha)
        try:
            if ABA not in wb.sheetnames: raise ValueError(f'Aba {ABA} não encontrada')
            ws=wb[ABA]; ultima=last_row(ws); modelo=model_formula(ws)
            existentes=set()
            for row in ws.iter_rows(min_row=2,max_row=ultima,min_col=2,max_col=6,values_only=True):
                lote, _cliente, produto, codigo, descricao = row
                if lote and codigo:
                    existentes.add((normal(lote),normal(produto),normal(codigo),normal(descricao)))
            inseridos=0; duplicados=0
            for reg in registros:
                k=chave(reg)
                if k in existentes:
                    duplicados+=1; continue
                dest=ultima+1
                copy_row(ws,ultima,modelo,dest)
                for col, key in enumerate(COLS,1):
                    value=reg.get(key)
                    if key=='data_programada' and value:
                        value=datetime.strptime(value,'%Y-%m-%d'); ws.cell(dest,col).number_format='dd/mm/yyyy'
                    ws.cell(dest,col).value=value
                if not ws.cell(dest,28).value: ws.cell(dest,28).value=f'=B{dest}&"|"&I{dest}'
                if not ws.cell(dest,29).value: ws.cell(dest,29).value=f'=IF($B{dest}="","","|"&SUBSTITUTE(TRIM($B{dest}&"")," ","|")&"|")'
                if not ws.cell(dest,30).value: ws.cell(dest,30).value=f'=TRIM($I{dest}&"")'
                existentes.add(k); ultima=dest; inseridos+=1
            if inseridos:
                pasta_backup.mkdir(parents=True,exist_ok=True)
                stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                backup=pasta_backup/f'{planilha.stem}_{stamp}.xlsx'
                shutil.copy2(planilha,backup)
                try:
                    wb.calculation.fullCalcOnLoad=True
                    wb.calculation.forceFullCalc=True
                except Exception: pass
                fd,tmp=tempfile.mkstemp(prefix='.j2i_',suffix='.xlsx',dir=planilha.parent)
                os.close(fd)
                try:
                    wb.save(tmp)
                    os.replace(tmp,planilha)
                finally:
                    if os.path.exists(tmp): os.unlink(tmp)
            return {'inseridos':inseridos,'duplicados':duplicados,'recebidos':len(registros)}
        finally:
            wb.close()
