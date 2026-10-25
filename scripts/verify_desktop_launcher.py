#!/usr/bin/env python3
"""Exercise the built Linux Tauri launcher against an explicitly disposable runtime home.

Requires tauri-driver, WebKitWebDriver, xdotool and a graphical session (or Xvfb + D-Bus).
Startup entries use a temporary XDG directory; all owned test processes are removed in finally.
"""
import argparse, ctypes, ctypes.util, json, os, signal, shutil, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--application', type=Path, required=True)
parser.add_argument('--runtime-home', type=Path, required=True)
parser.add_argument('--driver', type=Path, default=Path(shutil.which('tauri-driver') or 'tauri-driver'))
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--screenshot', action='store_true', help='Capture a native screenshot; requires compositor support in WebKitWebDriver')
args = parser.parse_args()
if sys.platform != 'linux': raise RuntimeError('This native acceptance helper currently requires Linux')
base = args.output.resolve().parent
base.mkdir(parents=True, exist_ok=True)
application = args.application.resolve()
runtime_home = args.runtime_home.resolve()
assert (runtime_home / '.luna-test-home').read_text() == 'disposable\n'
assert application.is_file() and shutil.which('xdotool')
preference_file = runtime_home / '.desktop-preferences.json'
prior_preferences = preference_file.read_bytes() if preference_file.exists() else None
preference_file.unlink(missing_ok=True)
configuration = runtime_home / "config.yaml"
prior_configuration = configuration.read_bytes()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def port():
    with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]
driver_port, native_port = port(), port()
url = f'http://127.0.0.1:{driver_port}'
def request(method,path,data=None,timeout=30):
    body = None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(url+path,data=body,method=method,headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=timeout) as response: result=json.load(response)['value']
    if isinstance(result,dict) and 'error' in result: raise RuntimeError(result)
    return result
def wait(callback,timeout=60):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            result=callback()
            if result:return result
        except (OSError,RuntimeError): pass
        time.sleep(.2)
    raise TimeoutError('Native control check did not become ready')
def pids():
    result=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():continue
        try:
            args=(entry/'cmdline').read_bytes().split(b'\0')
            if args[0]==os.fsencode(application) and os.fsencode(runtime_home) in args:result.append(int(entry.name))
        except OSError:pass
    return result
def windows(pid):
    result=subprocess.run(['xdotool','search','--onlyvisible','--pid',str(pid),'--name','^Luna$'],capture_output=True,text=True)
    return result.stdout.split()

def close_window(window):
    """Send WM_DELETE_WINDOW: a normal close request, not XDestroyWindow."""
    class Data(ctypes.Union):
        _fields_ = [('bytes', ctypes.c_char * 20), ('shorts', ctypes.c_short * 10), ('longs', ctypes.c_long * 5)]
    class Client(ctypes.Structure):
        _fields_ = [('type',ctypes.c_int),('serial',ctypes.c_ulong),('send_event',ctypes.c_int),('display',ctypes.c_void_p),('window',ctypes.c_ulong),('message_type',ctypes.c_ulong),('format',ctypes.c_int),('data',Data)]
    class Event(ctypes.Union):
        _fields_ = [('client',Client),('padding',ctypes.c_long * 24)]
    x11=ctypes.CDLL(ctypes.util.find_library('X11'))
    x11.XOpenDisplay.argtypes=[ctypes.c_char_p];x11.XOpenDisplay.restype=ctypes.c_void_p
    x11.XInternAtom.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int];x11.XInternAtom.restype=ctypes.c_ulong
    x11.XSendEvent.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_long,ctypes.POINTER(Event)]
    x11.XFlush.argtypes=[ctypes.c_void_p];x11.XCloseDisplay.argtypes=[ctypes.c_void_p]
    display=x11.XOpenDisplay(None)
    assert display
    try:
        event=Event();event.client.type=33;event.client.send_event=1;event.client.display=display
        event.client.window=int(window);event.client.format=32
        event.client.message_type=x11.XInternAtom(display,b'WM_PROTOCOLS',0)
        event.client.data.longs[0]=x11.XInternAtom(display,b'WM_DELETE_WINDOW',0)
        assert x11.XSendEvent(display,int(window),0,0,ctypes.byref(event))
        x11.XFlush(display)
    finally:x11.XCloseDisplay(display)

with tempfile.TemporaryDirectory(prefix='native-controls-',dir=base) as temporary:
    scratch=Path(temporary)
    env={k:v for k,v in os.environ.items() if not k.startswith(('LUNA_','HERMES_','HONCHO_','OPENAI_','OPENROUTER_')) and not k.endswith(('_KEY','_TOKEN','_SECRET','_PASSWORD'))}
    env.update(LUNA_HOME=str(runtime_home),HERMES_HOME=str(runtime_home),XDG_CONFIG_HOME=str(scratch/'config'),XDG_CACHE_HOME=str(scratch/'cache'),XDG_DATA_HOME=str(scratch/'data'),GDK_BACKEND='x11')
    session=None; pid=None
    logs=args.output.with_suffix('.driver.log').open('wb')
    driver=subprocess.Popen([str(args.driver.resolve()),'--port',str(driver_port),'--native-port',str(native_port)],env=env,stdout=logs,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        wait(lambda: request('GET','/status'))
        value=request('POST','/session',{'capabilities':{'alwaysMatch':{'tauri:options':{'application':str(application),'args':['--luna-home',str(runtime_home)]}}}},timeout=120)
        session=value['sessionId']; prefix='/session/'+session
        def execute(script,args=None):return request('POST',prefix+'/execute/sync',{'script':script,'args':args or []})
        def handles():return request('GET',prefix+'/window/handles')
        def switch(handle):return request('POST',prefix+'/window',{'handle':handle})
        def bootstrap():
            for handle in handles():
                switch(handle)
                if execute('return location.protocol')=='tauri:':return handle
            return None
        main=wait(bootstrap)
        def invoke(command,payload=None):
            value=request('POST',prefix+'/execute/async',{'script':"const done=arguments[arguments.length-1];window.__TAURI_INTERNALS__.invoke(arguments[0],arguments[1]).then(value=>done({ok:true,value}),error=>done({ok:false,error:String(error)}));",'args':[command,payload or {}]},timeout=90)
            if not value['ok']:raise RuntimeError(value['error'])
            return value.get('value')
        status=wait(lambda:invoke('luna_desktop_preferences'))
        assert not status['launch_at_login'] and not status['start_companion'] and not status['keep_in_background']
        assert status['tray_available']
        wait(lambda:len(handles())==2,120)
        switch(main)
        assert invoke('luna_set_desktop_preferences',{'patch':{'launch_at_login':True}})['launch_at_login']
        startup=scratch/'config/autostart/org.luna.companion.desktop'
        text=startup.read_text()
        assert '--background' in text and '"'+str(runtime_home)+'"' in text
        assert str(application) in text
        subprocess.run(['gio','launch',str(startup)],env=env,stdout=logs,stderr=subprocess.STDOUT,check=True,timeout=15)
        assert not invoke('luna_set_desktop_preferences',{'patch':{'launch_at_login':False}})['launch_at_login']
        assert not startup.exists()
        assert invoke('luna_set_desktop_preferences',{'patch':{'keep_in_background':True}})['keep_in_background']
        dashboard=next(handle for handle in handles() if handle!=main)
        switch(dashboard)
        endpoint=execute('return location.origin')
        denied=False
        try:invoke('luna_set_desktop_preferences',{'patch':{'launch_at_login':True}})
        except RuntimeError:denied=True
        assert denied and not startup.exists()
        # Use the dashboard's real API and wait for the separate native window
        # to adopt the same persisted palette, including its bundled typography.
        for name, canvas in [('sakura-day','#fbf0f8'),('mono','#0e0e0e'),('sakura-dusk','#17132b')]:
            switch(dashboard)
            changed=request('POST',prefix+'/execute/async',{'script':"const done=arguments[arguments.length-1];fetch('/api/dashboard/theme',{method:'PUT',headers:{'Content-Type':'application/json',Authorization:'Bearer '+window.__HERMES_SESSION_TOKEN__},body:JSON.stringify({name:arguments[0]})}).then(r=>done(r.status));",'args':[name]})
            assert changed==200
            switch(main)
            wait(lambda:execute('return document.documentElement.dataset.dashboardTheme')==name,15)
            assert execute("return document.documentElement.style.getPropertyValue('--background-base')")==canvas
            assert 'Manrope' in execute('return getComputedStyle(document.body).fontFamily')
        switch(main)
        if args.screenshot:
            screenshot=request('GET',prefix+'/screenshot')
            import base64
            args.output.with_suffix('.png').write_bytes(base64.b64decode(screenshot))
        pid=wait(lambda:next(iter(pids()),None))
        visible=wait(lambda:windows(pid))
        for window in visible:close_window(window)
        wait(lambda:not windows(pid))
        assert pid in pids() and not windows(pid)
        assert dashboard in handles()
        assert opener.open(endpoint+'/',timeout=10).status==200
        again=subprocess.Popen([str(application),'--luna-home',str(runtime_home)],env=env,stdout=logs,stderr=subprocess.STDOUT)
        assert again.wait(timeout=15)==0
        visible=wait(lambda:windows(pid))
        assert pids()==[pid]
        switch(main)
        try:invoke('luna_quit')
        except (OSError,RuntimeError):pass # The window may close before returning IPC.
        wait(lambda:pid not in pids(),30)
        result={'ok':True,'verified':['native webview startup','opt-in defaults','startup registration and removal','home paths containing spaces','saved background preference','dashboard native-permission denial','Sakura Dusk, Day and Mono synchronization','shared bundled typography','normal close keeps backend alive','second launch reopens existing window','explicit quit stops launcher']}
        args.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    finally:
        if session:
            try:request('DELETE','/session/'+session,timeout=10)
            except Exception:pass
        for process in pids():
            try:os.kill(process,signal.SIGTERM)
            except ProcessLookupError:pass
        try:os.killpg(driver.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:driver.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(driver.pid,signal.SIGKILL);driver.wait()
        logs.close()
        if prior_preferences is None:preference_file.unlink(missing_ok=True)
        else:preference_file.write_bytes(prior_preferences)
        configuration.write_bytes(prior_configuration)
