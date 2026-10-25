"""ON route runner built around the user's demo-day emergency behavior."""
import math
import queue
import threading
import time
import on_demo_original as demo
from kocoafab_robodog import RoboDog, FACE_RECOGNITION, 멍멍, 크게


def validate_route(config):
    if not isinstance(config, dict):
        raise ValueError('경로 설정이 필요합니다.')
    def number(value, low, high):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('코스 크기, 좌표 또는 보정값을 확인하세요.')
        return float(value)
    width=number(config.get('width'),10,300)
    height=number(config.get('height'),10,300)
    order=config.get('order')
    if order not in ('ABC','ACB','BAC','BCA','CAB','CBA'):
        raise ValueError('순찰 순서가 올바르지 않습니다.')
    source=config.get('points',{})
    points={}
    for key in ('S','A','B','C'):
        p=source.get(key,{})
        points[key]={'x':number(p.get('x'),0,width),'y':number(p.get('y'),0,height)}
    keys=['S',*order,'S']
    if any(math.hypot(points[a]['x']-points[b]['x'],points[a]['y']-points[b]['y'])<1 for a,b in zip(keys,keys[1:])):
        raise ValueError('인접 경로 점은 1cm 이상 떨어뜨려 주세요.')
    return dict(width=width,height=height,order=order,points=points,
        cm_per_sec=number(config.get('cm_per_sec',5),.1,100),
        initial_heading=number(config.get('initial_heading',0),-180,180))


class RoutePatrol:
    """Same nonblocking tick loop as SquarePatrol, with relative turns and timed legs."""
    def __init__(self,dog,eyes,config,targets=None,repeat=True):
        self.dog,self.eyes,self.config=dog,eyes,config
        self.keys=['S',*(targets if targets is not None else [*config['order'],'S'])];self.index=1
        self.repeat=repeat;self.finished=False
        self.x=config['points']['S']['x'];self.y=config['points']['S']['y']
        self.heading=config['initial_heading'];self.phase='PLAN';self.laps=0
        self.deadline=0;self.walk_start=0;self.turn_start=0;self.turn_angle=0
    def position(self):
        heading=self.heading
        if self.phase=='TURN':
            angle=self.dog.get_rotation()
            if isinstance(angle,(int,float)) and math.isfinite(angle) and abs(angle)<=abs(self.turn_angle)+15:
                heading=self.turn_start+angle
        return dict(x_cm=round(self.x,1),y_cm=round(self.y,1),heading_deg=round(heading,1),target=self.keys[self.index],phase=self.phase,laps=self.laps,position_estimated=True)
    def update_walk(self,now):
        elapsed=min(max(0,now-self.walk_start),self.distance/self.config['cm_per_sec'])
        traveled=elapsed*self.config['cm_per_sec']
        self.x=self.start_x+math.cos(math.radians(self.heading))*traveled
        self.y=self.start_y+math.sin(math.radians(self.heading))*traveled
    def pause(self,now=None):
        now=time.monotonic() if now is None else now
        if self.phase=='WALK':self.update_walk(now)
        elif self.phase=='TURN':
            angle=self.dog.get_rotation()
            if isinstance(angle,(int,float)) and math.isfinite(angle) and abs(angle)<=abs(self.turn_angle)+15:
                self.heading=self.turn_start+angle
        self.dog.move(0);self.dog.gesture(0);self.eyes.restore();self.phase='PLAN'
    def tick(self,now):
        if self.finished:return
        if self.phase=='PLAN':
            target=self.config['points'][self.keys[self.index]]
            dx,dy=target['x']-self.x,target['y']-self.y
            self.distance=math.hypot(dx,dy)
            if self.distance<.5:
                self.x,self.y=target['x'],target['y'];self.index+=1
                if self.index==len(self.keys):
                    if self.repeat:self.index=1;self.laps+=1
                    else:self.index-=1;self.finished=True;self.phase='ARRIVED'
                return
            self.target_heading=math.degrees(math.atan2(dy,dx))
            self.turn_angle=int(round((self.target_heading-self.heading+180)%360-180))
            self.dog.move(0);self.dog.gesture(0);self.eyes.restore()
            self.deadline=now+.5;self.phase='TURN_READY'
        elif self.phase=='TURN_READY' and now>=self.deadline:
            if abs(self.turn_angle)<=2:
                self.heading=self.target_heading;self.phase='WALK_READY';self.deadline=now+.4
            else:
                self.turn_start=self.heading;self.dog.rotate(self.turn_angle,demo.TURN_SPEED)
                self.deadline=now+demo.TURN_TIMEOUT;self.turn_requested_at=now;self.phase='TURN'
        elif self.phase=='TURN':
            angle=self.dog.get_rotation()
            if now-self.turn_requested_at>=.3 and isinstance(angle,(int,float)) and abs(angle-self.turn_angle)<=8:
                self.dog.move(0);self.dog.gesture(0);self.eyes.restore()
                self.heading=self.target_heading;self.phase='WALK_READY';self.deadline=now+.4
            elif now>=self.deadline:
                self.dog.move(0);raise RuntimeError('회전 확인 실패: 로보독을 정지했습니다.')
        elif self.phase=='WALK_READY' and now>=self.deadline:
            self.start_x,self.start_y=self.x,self.y;self.walk_start=now
            self.dog.move(demo.MOVE_SPEED);self.deadline=now+self.distance/self.config['cm_per_sec'];self.phase='WALK'
        elif self.phase=='WALK':
            self.update_walk(now)
            if now>=self.deadline:
                self.dog.move(0);self.dog.gesture(0);self.eyes.restore();self.phase='PLAN'


class PatrolService:
    SEARCH_SECONDS = 3.0
    MAX_ATTEMPTS = 5
    def __init__(self,publish):
        self.publish=publish;self.stop_event=threading.Event()
        self.inbox=queue.Queue(maxsize=64);self.commands=queue.Queue(maxsize=16)
        self.active=False;self.lock=threading.Lock();self.gate=demo.MessageGate();self.hazard_resume=threading.Event()
        self.sequence=0;self.latest_alert=None;self.snapshot={};self.notifications=[]
    def emit(self,**values):
        with self.lock:
            self.snapshot={**self.snapshot,**values}
            if 'x_cm' in values and 'y_cm' in values:
                point={'x':values['x_cm'],'y':values['y_cm']}
                trail=list(self.snapshot.get('trail',[]))
                if not trail or trail[-1]!=point:trail.append(point)
                self.snapshot['trail']=trail[-500:]
            result=dict(self.snapshot)
        self.publish(result)
    def notify(self,message,kind='info',**extra):
        with self.lock:
            self.sequence+=1
            item=dict(id=self.sequence,message=message,kind=kind,**extra)
            self.notifications=(self.notifications+[item])[-30:]
        self.emit(notifications=list(self.notifications))
    def signal(self,text):
        parsed=demo.parse_message(text)
        if not parsed:return False
        message=''.join(parsed)
        with self.lock:
            if not self.gate.is_new_event(message,time.monotonic()):return True
            self.sequence+=1
            alert=dict(id=self.sequence,code=message,kind=parsed[0],station=parsed[1],label=demo.KINDS[parsed[0]])
            self.latest_alert=alert
        # Every distinct alert interrupts motion and requires a new decision.
        if self.active:
            try:self.inbox.put_nowait(alert)
            except queue.Full:self.stop_event.set()
        else:self.emit(alert=alert,decision_pending=True,state='재난 신호 수신 · 관제 선택 대기',running=False)
        return True
    def decide(self,action,areas=None,alert_id=None):
        if action not in ('evacuate','return','hold'):raise ValueError('관제 명령을 확인하세요.')
        if not isinstance(areas or [],list):raise ValueError('대상 지역을 확인하세요.')
        areas=list(dict.fromkeys(areas or []))
        if action=='evacuate' and (not areas or any(a not in ('A','B','C') for a in areas)):
            raise ValueError('A·B·C 중 안내할 지역을 선택하세요.')
        with self.lock:
            alert=self.latest_alert
            if not alert or alert_id!=alert['id']:raise ValueError('최신 재난 알림에서 다시 선택하세요.')
        if not self.active:raise ValueError('ON 로보독을 연결하고 순찰을 시작한 뒤 대응하세요.')
        try:self.commands.put_nowait(dict(action=action,areas=areas,alert_id=alert_id))
        except queue.Full:raise ValueError('명령 처리 중입니다. 잠시 후 다시 시도하세요.')
    def resume_after_hazard(self):
        with self.lock:
            if not self.active or not self.snapshot.get('hazard_wait'):
                raise ValueError('현재 CLASS1 위험 정지 상태가 아닙니다.')
            if not self.snapshot.get('hazard_clear_confirmed'):
                raise ValueError('CLASS1이 사라지고 AI 연결이 확인된 뒤 재개할 수 있습니다.')
        self.hazard_resume.set()
    def prepare(self):
        self.stop_event.clear();self.hazard_resume.clear()
        for inbox in (self.inbox,self.commands):
            while not inbox.empty():
                try:inbox.get_nowait()
                except queue.Empty:break
        self.active=True
        if self.latest_alert:self.inbox.put_nowait(self.latest_alert)
    def run(self,port,config,dog_factory=RoboDog,speech_factory=demo.start_speech):
        dog=None;connected=False;nav=None
        self.emit(running=True,connected=False,x_cm=config['points']['S']['x'],y_cm=config['points']['S']['y'],heading_deg=config['initial_heading'],trail=[],run_id=time.monotonic_ns(),position_estimated=True,state='ON 로보독 연결 중',route=config,error='',decision_pending=False,mission='PATROL',search_attempt=0,notifications=list(self.notifications),hazard_wait=False,hazard_clear_confirmed=False)
        try:
            dog=dog_factory();connected=dog.Open(port) is not False
            if not connected:raise RuntimeError(f'ON 로보독 {port} 연결 실패')
            self.emit(connected=True,state='순찰 준비 중')
            if self.stop_event.wait(2):return
            eyes=demo.EyeDisplay(dog);dog.move(0);eyes.clear();dog.bodyLED(0x0F,0,255,0)
            dog.ai_mode(FACE_RECOGNITION,timeout=1.0)
            nav=RoutePatrol(dog,eyes,config);phase='PATROL';areas=[];area=None;alert=None
            attempts=0;deadline=0;last_publish=0;detected_streak=0
            hazard=False;hazard_since=0;clear_streak=0
            self.emit(state='순찰 중')
            def move_to(target):
                nonlocal nav
                old=nav
                nav=RoutePatrol(dog,eyes,config,targets=[target],repeat=False)
                nav.x,nav.y,nav.heading=old.x,old.y,old.heading
            def bark():
                dog.sound(멍멍,크게)
                eyes.restore()
            while not self.stop_event.is_set():
                now=time.monotonic()
                for _ in range(64):
                    try:incoming=self.inbox.get_nowait()
                    except queue.Empty:break
                    nav.pause(now);alert=incoming;areas=[];phase='WAIT';dog.bodyLED(0x0F,255,0,0);eyes.show(alert['kind']);bark()
                    self.emit(alert=alert,decision_pending=True,mission='WAIT',state='재난 신호 수신 · 관제 선택 대기',event_id=alert['id'],last_signal=alert['code'])
                ai_alive=bool(dog.is_ai_alive())
                ai_class=dog.get_face_recognition_class() if ai_alive else None
                if ai_class==1 and not hazard:
                    nav.pause(now);hazard=True;hazard_since=now;clear_streak=0;self.hazard_resume.clear()
                    dog.bodyLED(0x0F,255,0,0);bark()
                    self.notify('CLASS1 위험 대상 감지: 로보독이 정지하고 짖었습니다. 현장 확인 후 관제에서 재개하세요.','warning',event='CLASS1')
                    self.emit(state='CLASS1 감지 · 위험 정지',hazard_wait=True,hazard_clear_confirmed=False,ai_class=1,**nav.position())
                if hazard:
                    clear_streak=clear_streak+1 if ai_alive and ai_class!=1 else 0
                    cleared=clear_streak>=3
                    if self.hazard_resume.is_set() and cleared:
                        self.hazard_resume.clear();hazard=False
                        if phase=='SEARCH':deadline+=now-hazard_since
                        dog.bodyLED(0x0F,255 if alert else 0,0 if alert else 255,0);eyes.restore()
                        self.notify('CLASS1 해제 및 관제 확인 완료 · 중단했던 작업을 재개합니다.','info')
                        self.emit(hazard_wait=False,hazard_clear_confirmed=False,state='위험 정지 해제 · 작업 재개')
                    else:
                        self.emit(hazard_wait=True,hazard_clear_confirmed=cleared,ai_class=ai_class,
                            state='CLASS1 해제 확인 · 관제 재개 대기' if cleared else 'CLASS1 감지 또는 AI 확인 불가 · 정지 유지')
                        self.stop_event.wait(.03)
                        continue
                for _ in range(16):
                    try:command=self.commands.get_nowait()
                    except queue.Empty:break
                    if not alert or command['alert_id']!=alert['id']:continue
                    if phase not in ('WAIT','HOLD'):
                        self.notify('진행 중인 대응이 있습니다. 정지 후 다시 선택하세요.','warning');continue
                    if command['action']=='hold':
                        phase='HOLD';self.emit(decision_pending=True,mission=phase,state='현 위치 정지 유지')
                    elif command['action']=='return':
                        move_to('S');phase='RETURN';self.emit(decision_pending=False,mission=phase,state='관제 명령 · S로 복귀 중')
                    else:
                        areas=list(command['areas']);area=areas.pop(0);move_to(area);phase='VISIT'
                        self.emit(decision_pending=False,mission=phase,state=f'{area}지역 재난 안내 출동',selected_areas=[area,*areas],current_area=area)
                if phase in ('PATROL','VISIT','ESCORT','RETURN'):
                    nav.tick(now)
                    if nav.finished:
                        if phase=='VISIT':
                            dog.move(0);dog.ai_mode(FACE_RECOGNITION,timeout=1.0)
                            eyes.restore();attempts=1;detected_streak=0;bark();deadline=now+self.SEARCH_SECONDS;phase='SEARCH'
                            self.emit(mission=phase,state=f'{area}지역 집주인 확인 1/5 · CLASS{ord(area)-ord("A")+2}',search_attempt=attempts)
                        elif phase=='ESCORT' and areas:
                            area=areas.pop(0);move_to(area);phase='VISIT'
                            self.notify('S 대피 안내 도착 · 다음 선택 지역으로 이동합니다.')
                            self.emit(mission=phase,state=f'{area}지역 재난 안내 출동',current_area=area,search_attempt=0)
                        else:
                            dog.move(0);phase='COMPLETE'
                            self.emit(mission=phase,state='S 복귀 완료 · 관제 대기',decision_pending=False)
                            self.notify('대피 안내 후 S에 도착했습니다.' if self.snapshot.get('mission_outcome')=='found' else 'S 복귀를 완료했습니다.')
                elif phase=='SEARCH':
                    target=ord(area)-ord('A')+2
                    found=dog.is_ai_alive() and dog.get_face_recognition_class()==target
                    detected_streak=detected_streak+1 if found else 0
                    if detected_streak>=2:
                        bark();eyes.show(alert['kind']);dog.bodyLED(0x0F,255,0,0)
                        self.notify(f'{area}지역 집주인 CLASS{target} 확인 · 로보독이 S까지 대피를 안내합니다.','success',area=area)
                        move_to('S');phase='ESCORT'
                        self.emit(mission=phase,state=f'{area}지역 집주인 확인 · S로 대피 안내 중',mission_outcome='found',ai_class=target,position_estimated=True)
                    elif now>=deadline:
                        if attempts>=self.MAX_ATTEMPTS:
                            self.notify(f'{area}지역 인물을 확인하지 못했습니다. 5회 확인 후 S로 복귀합니다.','warning',area=area)
                            areas=[];move_to('S');phase='RETURN'
                            self.emit(mission=phase,state='인물을 확인하지 못했습니다 · S 복귀 중',mission_outcome='not_found',search_attempt=5)
                        else:
                            attempts+=1;bark();deadline=now+self.SEARCH_SECONDS;detected_streak=0
                            self.emit(search_attempt=attempts,state=f'{area}지역 집주인 확인 {attempts}/5 · CLASS{target}')
                if now-last_publish>=.15:
                    self.emit(**nav.position());last_publish=now
                self.stop_event.wait(.03)
        except Exception as exc:
            self.notify(f'ON 대응 오류: {exc}','error')
            self.emit(state='오류로 정지',error=str(exc))
        finally:
            try:
                if connected:
                    try:dog.move(0)
                    finally:dog.Close()
            finally:
                self.active=False
                self.emit(running=False,connected=False,hazard_wait=False,hazard_clear_confirmed=False,state='오류로 정지' if self.snapshot.get('error') else '순찰 정지')
