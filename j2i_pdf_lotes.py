"""Importador do layout TEGA/Dobue, sem OCR: ignora páginas inválidas e relata avisos."""
import io
import re
from pypdf import PdfReader


def extrair(conteudo, interpretar, avisos=None):
    leitor = PdfReader(io.BytesIO(conteudo))
    fichas, erros = [], []
    vistos = set()
    for pagina, pdf in enumerate(leitor.pages, 1):
        try:
            texto = pdf.extract_text(extraction_mode='layout') or ''
        except Exception as exc:
            erros.append(f'página {pagina}: leitura indisponível ({exc})'); continue
        if not texto.strip():
            erros.append(f'página {pagina}: sem texto pesquisável'); continue
        # O código numérico está na linha seguinte ao título O.P.; os demais
        # caracteres são glifos da fonte de código de barras, não o valor lido.
        m = re.search(r'O\.P\.[^\n]*\n[^\n]*?\b(\d{8})\b', texto)
        if not m and fichas and 'O.P.' not in texto and 'TEGA(relOrdemProducao)' in texto and re.search(r'^\s*\d+\s+.+\d+,\d+', texto, re.M):
            continue  # continuação de matéria-prima, sem nova OP
        if not m:
            erros.append(f'página {pagina}: OP ausente'); continue
        op = m.group(1)
        texto_base = re.sub(r'O\.P\.[^\n]*\n[^\n]*', 'O.P. '+op+' MATERIAL', texto, count=1)
        try:
            ficha = interpretar(texto_base, pagina)
        except Exception as exc:
            erros.append(f'página {pagina}, OP {op}: interpretação indisponível ({exc})'); continue
        ficha['tipo_material'] = ''
        ficha['rotas'] = []
        secao = False
        for linha in texto.splitlines():
            if re.match(r'\s*Setor\s+Equipamento', linha):
                secao = True; continue
            if 'R E S U M O' in linha or 'RESUMO DE' in linha:
                secao = False
            if not secao: continue
            rota = re.match(r'^\s*(\d+)\s+(.+?)\s{2,}(\d+)\s+(.+?)\s+(\d+)\s*$', linha)
            if not rota: continue
            partes = re.split(r'\s{2,}', rota.group(4).strip(), maxsplit=1)
            if len(partes)==1 and partes[0].endswith(rota.group(2).strip()):
                operacao=rota.group(2).strip()
                partes=[partes[0][:-len(operacao)].strip(),operacao]
            ficha['rotas'].append(dict(ordem=len(ficha['rotas'])+1,
                codigo_setor=rota.group(1),setor=rota.group(2).strip(),
                codigo_equipamento=rota.group(3), equipamento=partes[0],
                operacao=partes[1] if len(partes)>1 else '',pecas_por_vez=int(rota.group(5))))
        if not ficha['lote'] or not ficha['descricao_peca'] or not ficha['rotas'] or ficha['quantidade_produzir']<=0:
            erros.append(f'página {pagina}, OP {op}: lote, peça, quantidade ou roteiro incompleto'); continue
        if op in vistos:
            erros.append(f'página {pagina}, OP {op}: OP repetida no PDF; mantida a primeira página válida'); continue
        vistos.add(op)
        fichas.append(ficha)
    if avisos is not None:
        avisos.extend(erros)
    if not fichas:
        raise ValueError('Nenhuma OP válida no PDF. ' + '; '.join(erros))
    return fichas


def filtrar_equipamentos(fichas, equipamentos, avisos):
    """Aceita etapas somente pelo código do equipamento ativo, sem validar setor."""
    import copy
    codigos = {str(e['codigo']).strip().lstrip('0') for e in equipamentos if e.get('ativo', 1)}
    resultado = []
    for original in fichas:
        ficha = copy.deepcopy(original)
        rotas = []
        for rota in ficha['rotas']:
            codigo = str(rota.get('codigo_equipamento', '')).strip().lstrip('0')
            if codigo not in codigos:
                avisos.append(f"página {ficha.get('pagina_pdf', '?')}, OP {ficha['op']}: equipamento {codigo} não cadastrado; etapa {rota['ordem']} ignorada")
                continue
            rotas.append(rota)
        ficha['rotas'] = rotas
        if rotas:
            resultado.append(ficha)
        else:
            avisos.append(f"página {ficha.get('pagina_pdf', '?')}, OP {ficha['op']}: página ignorada, nenhuma etapa de equipamento ativo cadastrado")
    return resultado


# Compatibilidade com integrações antigas; o setor não participa do filtro.
filtrar_setores = filtrar_equipamentos
