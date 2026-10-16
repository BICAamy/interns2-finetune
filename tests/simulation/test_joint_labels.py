import numpy as np
from simulation.entry_point_env.joint_labels import project_joint_labels


def transforms():
    result=[]
    for index in range(6):
        item=np.eye(4);item[:3,3]=(index*100,index*20,300);result.append(item)
    return result


def test_joint_centers_follow_the_fk_transforms_without_mutating_them():
    links=transforms();before=[link.copy() for link in links];seen=[]
    def project(point):
        seen.append(point.copy());return (100+point[1]*100,100+point[0]*100)
    labels=project_joint_labels(links,(300,400,3),project)
    assert [label['name'] for label in labels]==['J1','J2','J3','J4','J5','J6']
    for index,(point,original,current) in enumerate(zip(seen,before,links)):
        np.testing.assert_allclose(point,original[:3,3]/1000)
        np.testing.assert_array_equal(original,current)
        assert labels[index]['x']==(100+index*10)/400


def test_offscreen_joint_numbers_are_not_renumbered():
    labels=project_joint_labels(transforms(),(100,100,3),lambda p:(50,-10 if p[0]<.15 else 50))
    assert [label['joint'] for label in labels]==[3,4,5,6]


def test_invalid_projection_is_omitted_instead_of_breaking_the_frame():
    def project(_):raise ZeroDivisionError('camera near plane')
    assert project_joint_labels(transforms(),(100,100,3),project)==()
    assert project_joint_labels(transforms(),(100,100,3),lambda p:(float('nan'),20))==()


def test_cached_joint_projection_api_is_read_only():
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from tests.integration.test_simulation_api import ControllerEnvironment
    from simulation.server.api import create_app
    from simulation.server.simulation_worker import SimulationWorker
    class LabelEnvironment(ControllerEnvironment):
        def reset(self,*args,**kwargs):
            observation=super().reset(*args,**kwargs)
            return SimpleNamespace(state=observation.state,joint_positions_deg=observation.joint_positions_deg,
                rgb=observation.rgb,joint_labels=({'joint':1,'name':'J1','x':.2,'y':.3},))
    worker=SimulationWorker(LabelEnvironment,tick_interval_s=.01)
    with TestClient(create_app(worker)) as client:
        before=worker.get_telemetry().state.model_dump()
        data=client.get('/v1/visualization/joint-labels').json()
        assert data['labels'][0]['name']=='J1'
        copy=worker.get_joint_labels();copy['labels'][0]['name']='changed'
        assert worker.get_joint_labels()['labels'][0]['name']=='J1'
        assert worker.get_telemetry().state.model_dump()==before
