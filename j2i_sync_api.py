"""API vinculada somente a 127.0.0.1; proteger rota Cloudflare Access e token adicional."""
import os, json, time, uuid, sqlite3, threading, logging, hmac
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel, Field, field_validator
from j2i_importer import importar

ROOT=Path(__file__).resolve().parent
PLANILHA=Path(os.environ.get('J2I_EXCEL_PATH',str(ROOT/'PPCP_ACOMPAN.xlsx'))).resolve()
STATE=Path(os.environ.get('J2I_SYNC_STATE',str(ROOT/'j2i_sync_data'))).resolve()
STATE.mkdir(parents=True,exist_ok=True)
DATABASE=STATE/'fila.sqlite3'; BACKUPS=STATE/'backups'
TOKEN=os.environ.get('J2I_SYNC_API_KEY','')
if len(TOKEN)<32: raise RuntimeError('Defina J2I_SYNC_API_KEY com pelo menos 32 caracteres aleatorios.')
app=FastAPI(title='J2I PCP Sync API',docs_url=None,redoc_url=None,openapi_url=None)
log=logging.getLogger('j2i-sync')

def db():
    con=sqlite3.connect(DATABASE,timeout=30)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA busy_timeout=30000')
    return con

def init():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('''CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
            result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

class Record(BaseModel):
    data_programada: str|None=None
    op_lote: str=Field(min_length=1,max_length=180)
    cliente_pedido: str=Field(default='',max_length=800)
    produto_equipamento: str=Field(min_length=1,max_length=500)
    codigo_peca: str=Field(min_length=1,max_length=180)
    descricao_peca: str=Field(default='',max_length=800)
    operacao: str=Field(default='',max_length=500)
    setor: str=Field(default='',max_length=500)
    maquina_posto: str=Field(default='',max_length=500)
    qtde_programada: float=Field(ge=0,le=1e9)
    @field_validator('data_programada')
    @classmethod
    def check_date(cls,v):
        if v: datetime.strptime(v,'%Y-%m-%d')
        return v

class Batch(BaseModel):
    batch_id: uuid.UUID
    registros: list[Record]=Field(min_length=1,max_length=1000)

def auth(x_j2i_api_key):
    if not x_j2i_api_key or not hmac.compare_digest(x_j2i_api_key,TOKEN):
        raise HTTPException(401,'Credencial invalida')

@app.post('/v1/pcp/batches',status_code=202)
def receive(batch:Batch,x_j2i_api_key:str|None=Header(default=None)):
    auth(x_j2i_api_key)
    ident=str(batch.batch_id); payload=batch.model_dump_json(); now=datetime.now(timezone.utc).isoformat()
    with db() as con:
        row=con.execute('SELECT payload,state FROM batches WHERE id=?',(ident,)).fetchone()
        if row:
            if json.loads(row['payload'])!=json.loads(payload): raise HTTPException(409,'ID de envio ja utilizado com outro conteudo')
            return {'batch_id':ident,'state':row['state']}
        con.execute('INSERT INTO batches VALUES (?,?,?,?,?,?,?)',(ident,payload,'pending',None,None,now,now))
    return {'batch_id':ident,'state':'pending'}

@app.get('/v1/pcp/batches/{batch_id}')
def status(batch_id:uuid.UUID,x_j2i_api_key:str|None=Header(default=None)):
    auth(x_j2i_api_key)
    with db() as con: row=con.execute('SELECT state,result,error FROM batches WHERE id=?',(str(batch_id),)).fetchone()
    if not row: raise HTTPException(404,'Envio nao encontrado')
    return {'batch_id':str(batch_id),'state':row['state'],
            'result':json.loads(row['result']) if row['result'] else None,'error':row['error']}

@app.get('/health')
def health(): return {'status':'ok'}

_stop=threading.Event()
def work_loop():
    while not _stop.is_set():
        try:
            with db() as con:
                row=con.execute("SELECT id,payload FROM batches WHERE state IN ('pending','processing') ORDER BY created_at LIMIT 1").fetchone()
                if row: con.execute("UPDATE batches SET state='processing',updated_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),row['id']))
            if not row:
                _stop.wait(1);continue
            try:
                registros=json.loads(row['payload'])['registros']
                result=importar(PLANILHA,registros,BACKUPS)
                state='completed'; error=None
            except Exception as exc:
                result=None;state='failed';error=str(exc)[:1000];log.exception('Erro importando %s',row['id'])
            with db() as con:
                con.execute('UPDATE batches SET state=?,result=?,error=?,updated_at=? WHERE id=?',
                    (state,json.dumps(result) if result else None,error,datetime.now(timezone.utc).isoformat(),row['id']))
        except Exception: log.exception('Falha no loop');_stop.wait(5)

@app.on_event('startup')
def startup():
    init(); _stop.clear();threading.Thread(target=work_loop,daemon=True,name='j2i-pcp-worker').start()
@app.on_event('shutdown')
def shutdown(): _stop.set()
