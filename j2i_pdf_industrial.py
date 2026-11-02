"""Leitura por coordenadas dos relatórios TEGA enviados em 23/10/2026.

Não une códigos de materiais de revestimentos diferentes. PDF desconhecido
ou linha numérica incompleta causa erro, evitando importação silenciosa parcial.
"""
import io
import re
import unicodedata
from decimal import Decimal
import fitz


def normal(texto):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(texto)) if not unicodedata.combining(c)).upper().split())


def br(texto):
    if not re.fullmatch(r'-?[\d.]+,\d+', texto.strip()):
        raise ValueError(f'Número brasileiro não reconhecido: {texto!r}')
    return float(Decimal(texto.replace('.', '').replace(',', '.')))


class Pagina:
    def __init__(self, pg):
        self.spans = [s for b in pg.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]
        self.chars = [ch for b in pg.get_text('rawdict')['blocks'] for l in b.get('lines',[]) for s in l['spans'] for ch in s['chars']]
        self.ys = {}
        for ch in self.chars:
            self.ys.setdefault(int(ch['origin'][1]), []).append(ch)
        self.texto = pg.get_text()

    def faixa(self, x0, x1, y, tol=1.2):
        return ''.join(c['c'] for c in sorted([ch for k in range(int(y-tol)-1,int(y+tol)+2) for ch in self.ys.get(k,[])], key=lambda c:c['origin'][0])
                       if x0 <= c['origin'][0] < x1 and abs(c['origin'][1]-y) <= tol).strip()

    def campo(self, x0, x1, y0, y1):
        return ' '.join(s['text'].strip() for s in self.spans if x0 <= s['origin'][0] < x1 and y0 <= s['origin'][1] < y1).strip()


def estoque(conteudo):
    linhas, vistos = [], set()
    local = None
    with fitz.open(stream=conteudo, filetype='pdf') as doc:
        for n, pg in enumerate(doc, 1):
            p = Pagina(pg)
            if 'RelConferenciaEstoqueFonteMaior' not in p.texto:
                raise ValueError(f'Página {n}: não é o layout TEGA de conferência de estoque validado.')
            match = re.search(r'Local\.:\s*(\d+)', p.texto)
            if match:
                if local and local != match[1]:
                    raise ValueError('Importe um único local de estoque por arquivo.')
                local = match[1]
            anchors = [s for s in p.spans if 20 < s['origin'][0] < 25 and 60 < s['origin'][1] < 801 and s['text'].strip().isdigit()]
            for s in anchors:
                y = s['origin'][1]
                codigo = s['text'].strip().lstrip('0') or '0'
                desc = p.faixa(75, 275, y)
                revest = p.faixa(275, 388, y)
                rm = re.match(r'(\d+)\s*(.*)', revest)
                un = p.faixa(388, 420, y)
                saldo = p.faixa(420, 474, y)
                if not rm or not un or not desc:
                    raise ValueError(f'Página {n}, material {codigo}: colunas incompletas.')
                rev, nome = rm.groups()
                if not local:
                    raise ValueError('Local de estoque não identificado no cabeçalho.')
                chave = f'{local}:{codigo}:{int(rev)}'
                if chave in vistos:
                    raise ValueError(f'Estoque repetido: {chave}. Confira o relatório.')
                vistos.add(chave)
                linhas.append(dict(codigo=chave, produto=codigo, local=local, revestimento_codigo=str(int(rev)),
                                   revestimento=nome.strip(), descricao=desc, unidade=un, saldo=br(saldo), pagina=n))
    if not linhas:
        raise ValueError('Nenhum saldo reconhecido.')
    return linhas


def materias(p, depois=0):
    saida = []
    for s in p.spans:
        x, y = s['origin']
        if not (26 < x < 30 and depois < y < 800 and s['text'].strip().isdigit()):
            continue
        descricao = p.faixa(80, 245, y)
        revestimento = p.faixa(245, 410, y)
        bruto, perda, consumo = p.faixa(410, 460, y), p.faixa(460, 514, y), p.faixa(514, 570, y)
        if not descricao or not revestimento:
            raise ValueError('Linha de MP incompleta.')
        saida.append(dict(produto=s['text'].strip().lstrip('0') or '0', descricao=descricao,
                          revestimento=revestimento, base_por_peca=br(bruto), perda_percentual=br(perda),
                          consumo_por_peca=br(consumo)))
    return saida


def fichas(conteudo, avisos=None):
    resultado, vistos = [], set()
    with fitz.open(stream=conteudo, filetype='pdf') as doc:
        for n, pg in enumerate(doc, 1):
            p = Pagina(pg)
            if 'TEGA(relOrdemProducao)' not in p.texto:
                raise ValueError(f'Página {n}: layout de OP não reconhecido.')
            ops = [s['text'].strip() for s in p.spans if s['size'] > 20 and re.fullmatch(r'\d{8}', s['text'].strip())]
            if not ops:
                # Continuação conserva MP que o importador anterior descartava.
                mp = materias(p, 40)
                if not resultado or not mp:
                    raise ValueError(f'Página {n}: continuação sem OP anterior ou sem materiais reconhecidos.')
                resultado[-1]['materiais'].extend(mp)
                resultado[-1]['paginas_pdf'].append(n)
                continue
            if len(ops) != 1 or ops[0] in vistos:
                raise ValueError(f'Página {n}: OP duplicada/ambígua.')
            op = ops[0]; vistos.add(op)
            def campo(*args):return p.campo(*args)
            medida = campo(245, 350, 115, 128)
            qtd = campo(390, 440, 115, 128)  # Quantidade desta OP/palete; a coluna seguinte é o total da peça.
            qtd_total_peca = campo(440, 487, 115, 128)
            lote = campo(450, 500, 89, 102)
            ficha = dict(op=op, codigo_barras=op, lote=lote, codigo_peca=campo(70, 138, 104, 114),
                         descricao_peca=campo(145, 600, 104, 114), medida=medida,
                         codigo_revestimento=campo(95, 109, 115, 128), revestimento=campo(109, 215, 115, 128),
                         quantidade_material=br(qtd), quantidade_produzir=br(qtd), quantidade_total_peca=br(qtd_total_peca),
                         tipo_material='', obs_lote=campo(80, 350, 89, 100), emissao_data=campo(390, 430, 28, 40),
                         emissao_hora=campo(430, 470, 28, 40), pagina_pdf=n, paginas_pdf=[n], produtos=[], rotas=[], materiais=[])
            roteiro_y = next((s['origin'][1] for s in p.spans if s['text'].strip()=='Equipamento'), None)
            resumo_y = next((s['origin'][1] for s in p.spans if 'RESUMODEMP' in re.sub(r'\s+','',s['text'])), 800)
            if not roteiro_y:
                raise ValueError(f'Página {n}, OP {op}: roteiro ausente.')
            anchors = sorted([s for s in p.spans if 210<s['origin'][0]<239 and roteiro_y<s['origin'][1]<resumo_y and re.match(r'^\d+\b', s['text'].strip())], key=lambda s:s['origin'][1])
            for s in anchors:
                y=s['origin'][1]
                setor=p.faixa(20,210,y);sm=re.match(r'(\d+)\s+(.*)',setor)
                operacao=p.faixa(397,555,y)
                ficha['rotas'].append(dict(ordem=len(ficha['rotas'])+1,codigo_setor=sm[1] if sm else '',setor=sm[2] if sm else setor,
                    codigo_equipamento=p.faixa(210,240,y),equipamento=p.faixa(240,397,y),operacao=operacao,
                    pecas_por_vez=int(p.faixa(555,580,y) or 0)))
            # Produtos relacionados: guardados com colunas independentes.
            for s in p.spans:
                if 26<s['origin'][0]<29 and 150<s['origin'][1]<roteiro_y and s['text'].strip().isdigit():
                    y=s['origin'][1]
                    ficha['produtos'].append(dict(codigo=s['text'].strip(),descricao=p.faixa(98,272,y,3),
                        revestimento_cor=p.faixa(273,393,y,3),sequencia=p.faixa(394,435,y,3),
                        qtde_por_produto=br(p.faixa(440,505,y,3)),qtde_produzir=br(p.faixa(510,570,y,3))))
            ficha['materiais']=materias(p,resumo_y)
            if not lote.isdigit() or not ficha['descricao_peca'] or ficha['quantidade_produzir']<=0:
                raise ValueError(f'Página {n}, OP {op}: ficha incompleta.')
            resultado.append(ficha)
    if not resultado:
        raise ValueError('Nenhuma OP reconhecida.')
    return resultado
