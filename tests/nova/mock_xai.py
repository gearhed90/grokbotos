#!/usr/bin/env python3
"""Fake xAI /v1/chat/completions: maps twitch prompts to open_url, then replies."""
import io, json, os, re, wave
from http.server import HTTPServer, BaseHTTPRequestHandler
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self, d, ct):
        self.send_response(200);self.send_header('Content-Type',ct);self.send_header('Content-Length',str(len(d)));self.end_headers();self.wfile.write(d)
    def do_POST(self):
        raw=self.rfile.read(int(self.headers['Content-Length']))
        assert self.headers['Authorization'].startswith('Bearer ')
        if self.path.endswith('/stt'):   # multipart: options first, then a real WAV file
            assert raw.index(b'name="model"') < raw.index(b'name="file"')
            wav=raw.split(b'Content-Type: audio/wav\r\n\r\n',1)[1].rsplit(b'\r\n--',1)[0]
            w=wave.open(io.BytesIO(wav)); dur=w.getnframes()/w.getframerate()
            assert w.getnchannels()==1 and w.getframerate()==16000
            nf=os.environ.get('MOCK_STT_NEXT'); text=open(nf).read() if nf and os.path.exists(nf) else 'hello'
            return self._send(json.dumps({"text":text,"language":"en","duration":round(dur,2),"words":[]}).encode(),'application/json')
        if self.path.endswith('/tts'):
            j=json.loads(raw); assert j['language'] and j['voice_id'] and j['text']
            b=io.BytesIO(); w=wave.open(b,'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(b'\0\0'*2400*min(20,len(j['text'])//10+1)); w.close()
            return self._send(b.getvalue(),'audio/wav')
        req=json.loads(raw)
        msgs=req['messages']; last=msgs[-1]
        tm=re.match(r'^TOOL (\w+) ?(.*)$', next((x['content'] for x in reversed(msgs) if x['role']=='user'),'') or '')
        if tm and last['role']=='user':
            msg={"role":"assistant","content":None,"tool_calls":[{"id":"call_t","type":"function",
                 "function":{"name":tm.group(1),"arguments":tm.group(2) or "{}"}}]}
        elif tm:
            msg={"role":"assistant","content":"RESULT "+last['content']}
        elif last['role']=='tool':
            msg={"role":"assistant","content":"Opening burntpeanut's Twitch stream now."}
        else:
            u=last['content'].lower(); m=re.search(r'(?:bring up|open|play) (?:the )?(.+?) twitch',u)
            if m:
                ch=re.sub(r'[^a-z0-9_]','',m.group(1))
                msg={"role":"assistant","content":None,"tool_calls":[{"id":"call_1","type":"function",
                     "function":{"name":"open_url","arguments":json.dumps({"url":f"https://www.twitch.tv/{ch}"})}}]}
            else: msg={"role":"assistant","content":"Mock reply to: "+last['content']}
        d=json.dumps({"choices":[{"message":msg}]}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(d)));self.end_headers();self.wfile.write(d)
HTTPServer(('127.0.0.1',8799),H).serve_forever()
