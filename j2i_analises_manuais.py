"""Projeção de eventos realizados, separada das linhas únicas de programação."""
from collections import defaultdict
from datetime import datetime
import math
import pandas as pd

ATR_HISTORICO = 'j2i_historico_manual'
ATR_VALIDADO = 'j2i_historico_validado'
ID_COL = 'ID Apontamento Manual'


def carregar(wb, aba):
    from j2i_parciais import ABA_HISTORICO, CAMPOS
    if ABA_HISTORICO not in wb.sheetnames:
        return []
    ws=wb[ABA_HISTORICO]
    cabecalho=next(ws.iter_rows(min_row=1,max_row=1,values_only=True),())
    if list(cabecalho)!=CAMPOS:
        raise ValueError('Histórico manual com cabeçalho inválido. Corrija a aba de histórico antes de consultar as análises.')
    return [dict(zip(CAMPOS,r)) for r in ws.iter_rows(min_row=2,values_only=True) if any(v is not None for v in r) and r[6]==aba]


def texto(v):
    if v is None or pd.isna(v):return ''
    return str(int(v)) if isinstance(v,float) and v.is_integer() else str(v).strip()


def numero(v):
    try:x=float(v or 0)
    except (TypeError,ValueError):raise ValueError('Quantidade inválida no histórico manual.') from None
    if not math.isfinite(x) or x<0:raise ValueError('Quantidade inválida no histórico manual.')
    return x


def validar(df):
    """Nenhuma distribuição é inventada quando histórico e acumulado divergem."""
    historico=df.attrs.get(ATR_HISTORICO,[])
    if not historico:return {}
    por_id=defaultdict(list)
    ids_eventos=set()
    for evento in historico:
        identificador=texto(evento.get('Evento'))
        chave=texto(evento.get('ID linha'))
        if not identificador or identificador in ids_eventos or not chave:
            raise ValueError('Histórico manual com evento duplicado ou sem identificação. Análise interrompida para evitar dupla contagem.')
        ids_eventos.add(identificador);por_id[chave].append(evento)
    linhas={}
    if ID_COL in df.columns:
        ids = df[ID_COL].map(texto)
        preenchidos = ids.ne('')
        if ids[preenchidos].duplicated().any():
            raise ValueError('Identificador manual repetido na planilha. Revise as linhas copiadas.')
        # Materializa somente as linhas com histórico, não a planilha inteira.
        for r in df.loc[ids.isin(por_id)].to_dict('records'):
            linhas[texto(r[ID_COL])] = r
    for chave,eventos in por_id.items():
        if chave not in linhas:
            raise ValueError('Há lançamentos manuais sem a linha de origem na planilha. Restaure a linha/identificador antes de consultar as análises.')
        r=linhas[chave]
        anterior=0.0
        for evento in eventos:
            qtd=numero(evento['Quantidade lançada']);antes=numero(evento['Total anterior']);depois=numero(evento['Total apontado'])
            if not math.isclose(antes,anterior,rel_tol=1e-9,abs_tol=1e-7):
                raise ValueError(f"Linha {int(r['Linha Excel'])}: histórico incompleto. Há saldo anterior sem data preservada ou lançamento ausente. Não é seguro distribuir esse total pelos dias; regularize o histórico.")
            if not math.isclose(antes+qtd,depois,rel_tol=1e-9,abs_tol=1e-7):
                raise ValueError('O histórico manual contém totais inconsistentes. Análise interrompida.')
            if pd.isna(pd.to_datetime(evento.get('Data produção'),errors='coerce')):
                raise ValueError('Lançamento manual sem data válida. Nenhuma data será presumida.')
            for campo in ['OP/Lote','Código Peça','Setor','Máquina/Posto']:
                if texto(evento.get(campo))!=texto(r.get(campo)):
                    raise ValueError(f'Linha {int(r["Linha Excel"])}: lote/peça/setor/equipamento alterado após apontamento. Revise a identidade antes de analisar.')
            anterior=depois
        if not math.isclose(numero(r.get('Qtde Realizada')),anterior,rel_tol=1e-9,abs_tol=1e-7):
            raise ValueError(f'Linha {int(r["Linha Excel"])}: Qtde Realizada diverge do histórico manual. Análise interrompida para evitar resultados incorretos.')
    return dict(por_id)


def projetar(df):
    """Mantém legados sem histórico; substitui cada acumulado controlado por seus eventos."""
    if df.attrs.get('j2i_base_eventos'):
        return df.copy()
    por_id=validar(df)
    if not por_id:
        resultado=df.copy();resultado.attrs['j2i_base_eventos']=True;return resultado
    ids = df[ID_COL].map(texto)
    controladas = ids.isin(por_id)
    # Linhas antigas seguem em bloco. Expande apenas linhas que têm eventos.
    legado = df.loc[~controladas].copy()
    legado.attrs = {}
    legado['_ordem_projecao'] = [i for i, v in enumerate(controladas) if not v]
    saida=[]
    posicoes = [i for i, v in enumerate(controladas) if v]
    for ordem, linha in zip(posicoes, df.loc[controladas].to_dict('records')):
        for evento in por_id[texto(linha[ID_COL])]:
            quantidade=numero(evento['Quantidade lançada'])
            if quantidade<=0:continue
            r=linha.copy()
            data=pd.Timestamp(evento['Data produção']).date()
            r.update({'Qtde Realizada':quantidade,'Data Realizada Valor':data,'Data Realizada':data.strftime('%d/%m/%Y'),
                'Evento Manual':evento['Evento'],'Fonte Apontamento':'Histórico manual',
                'Qtde Programada':0.0,'Tempo Programado (min)':0.0,'Setup Padrão (min)':0.0,
                'Tempo Realizado (min)':'','Refugo/Retrabalho':'','_ordem_projecao':ordem})
            for campo in ['Setor','Máquina/Posto','Descrição Peça']:
                r[campo]=evento.get(campo) or r.get(campo)
            saida.append(r)
    resultado=pd.concat([legado,pd.DataFrame(saida)],ignore_index=True)
    resultado=resultado.sort_values('_ordem_projecao',kind='stable').drop(columns='_ordem_projecao').reset_index(drop=True)
    resultado=resultado.reindex(columns=list(dict.fromkeys([*df.columns,'Evento Manual','Fonte Apontamento'])))
    resultado.attrs={'j2i_base_eventos':True}
    return resultado


def classificar_prazos(base):
    """Distribui as quantidades por prazo sem multiplicar programação/linhas."""
    grupos=validar(base)
    if not grupos:return base
    ids = base[ID_COL].map(texto)
    selecionadas = base.loc[ids.isin(grupos)].copy()
    selecionadas.attrs = {}
    for indice,r in selecionadas.iterrows():
        eventos=grupos.get(texto(r.get(ID_COL)))
        if not eventos:continue
        prazo=pd.to_datetime(r['Data Programada DT'],errors='coerce')
        if pd.isna(prazo):continue
        saldo=numero(r['Qtde Programada Num']);no_prazo=apos=ponderado=0.0
        for e in sorted(eventos,key=lambda x:pd.Timestamp(x['Data produção'])):
            qtd=min(saldo,numero(e['Quantidade lançada']));saldo-=qtd
            dias=max(0,(pd.Timestamp(e['Data produção']).normalize()-prazo.normalize()).days)
            if dias:
                apos+=qtd;ponderado+=qtd*dias
            else:no_prazo+=qtd
        base.at[indice,'Realizada no Prazo Num']=no_prazo
        base.at[indice,'Realizada Após Num']=apos
        base.at[indice,'Pendente Num']=saldo
        vencido=prazo.normalize()<pd.Timestamp(datetime.now().date())
        base.at[indice,'Pendente Vencida Num']=saldo if vencido else 0
        base.at[indice,'Em Atraso Num']=apos+(saldo if vencido else 0)
        base.at[indice,'Atraso Realizado Ponderado Num']=ponderado
    return base
