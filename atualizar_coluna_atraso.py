import argparse,ast,hashlib,json,os
from datetime import datetime
from pathlib import Path

def instalar(destino,parado):
 if not parado:raise ValueError('Pare o MES e use --servidor-parado.')
 src=Path(__file__).resolve().parent;dest=Path(destino)
 manifesto=json.loads((src/'manifesto_coluna_atraso.json').read_text())
 for n,m in manifesto.items():
  b=(src/n).read_bytes();ast.parse(b)
  if hashlib.sha256(b).hexdigest()!=m['depois']:raise ValueError('Pacote alterado: '+n)
  p=dest/n
  if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() not in (m['antes'],m['depois']):raise ValueError('Versão diferente de '+n+'. Envie esse arquivo atual para compatibilização.')
  if m['antes'] and not p.exists():raise ValueError('Arquivo necessário ausente: '+n)
 for n in ('j2i_atrasos_equipamento.py','j2i_sessoes_producao.py','j2i_encerramento_ppcp.py'):
  ast.parse((dest/n).read_bytes())
 backup=dest/'backups'/('antes_coluna_atraso_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));backup.mkdir(parents=True)
 antigos={n:(dest/n).read_bytes() if (dest/n).exists() else None for n in manifesto}
 for n,b in antigos.items():
  if b is not None:(backup/n).write_bytes(b)
 try:
  for n in manifesto:
   tmp=dest/(n+'.atraso.tmp');tmp.write_bytes((src/n).read_bytes());os.replace(tmp,dest/n)
 except Exception:
  for n,b in antigos.items():
   if b is None:(dest/n).unlink(missing_ok=True)
   else:(dest/n).write_bytes(b)
  raise
 print(f'Atualizado. Backup: {backup}\nBancos preservados. Reinicie o MES.')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--destino',required=True);p.add_argument('--servidor-parado',action='store_true');a=p.parse_args();instalar(a.destino,a.servidor_parado)
