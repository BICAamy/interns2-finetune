#!/usr/bin/env python
# _*_ coding:utf-8 _*_
'''
*
*   All rights reserved.
*	
*	FileName:CPS.py
*	Descriptio:Python SDK
*   version:1.1.1.0
*	Modification Records:
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   SDK Version                    Date                                                      Add                                                            Modify                                                       Delete
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.0.0                       2022.05.12                                                Create a file
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.0.1                       2022.07.07                                                Create a interface
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.0.2                       2022.08.05                                                Create a interface
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.0.3                       2022.08.28                                                HRIF_SetToolMotion
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.0.4                       2023.02.13                                                HRIF_ReadOverride
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.0.5                       2023.02.13                                                HRIF_ReadPointByName
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.1.0                       2023.02.23                                                HRIF_GetErrorCodeStr
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.2.0                       2023.02.23                                                HRIF_SetPoseTrackingMaxMotionLimit
                                                                                             HRIF_SetPoseTrackingPIDParams
                                                                                             HRIF_SetPoseTrackingTargetPos
                                                                                             HRIF_SetPoseTrackingState
                                                                                             HRIF_SetUpdateTrackingPose
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.2.1                       2023.03.21                                                                                                               HRIF_IsBlendingDone
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.2.2                       2023.08.22                                                                                                               HRIF_ReadHoldingRegisters
                                                                                                                                                            HRIF_WriteHoldingregisters  
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.3.0                       2024.04.15                                                HRIF_SetSimulation
                                                                                             HRIF_OpenBrake
                                                                                             HRIF_CloseBrake
                                                                                             HRIF_ReadBrakeStatus
                                                                                             HRIF_MoveToSS
                                                                                             HRIF_SetCollideLevel
                                                                                             HRIF_ReadMaxPayload
                                                                                             HRIF_ReadPayload
                                                                                             HRIF_CalUcsPlane
                                                                                             HRIF_CalUcsLine
                                                                                             HRIF_CalTcp3P
                                                                                             HRIF_CalTcp4P
                                                                                             HRIF_ConfigTCP
                                                                                             HRIF_ConfigUCS
                                                                                             HRIF_HRSetMaxSearchDistance
                                                                                                                                                             HRIF_HRApp      
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*   V1.0.4.0                       2024.08.27                                                HRIF_EnableEndBTN
                                                                                             HRIF_ReadPointList
                                                                                             HRIF_ReadTCPList
                                                                                             HRIF_ReadUSCList
                                                                                             HRIF_SetFTFreeDriveSpeedMode
                                                                                             HRIF_ReadtFTFreeDriveSpeedMode
                                                                                             HRIF_ReadFTCabData
                                                                                             HRIF_SetFreeDriveMotionFreedom
                                                                                             HRIF_SetFTFreeFactor
                                                                                             HRIF_SetFreeDriveCompensateForce
                                                                                             HRIF_ReadFTMotionFreedom
                                                                                             HRIF_SetSteadyContactDeviationRange
                                                                                             HRIF_InitPath
                                                                                             HRIF_PushPathPoints
                                                                                             HRIF_EndPushPathPoints
                                                                                             HRIF_DelPath
                                                                                             HRIF_ReadPathList
                                                                                             HRIF_ReadPathInfo
                                                                                             HRIF_UpdataPathName
                                                                                             HRIF_ReadPathState
                                                                                             HRIF_MoveLinearWeave
                                                                                             HRIF_MoveCircularWeave
                                                                                             HRIF_ReadServoEsJState
                                                                                                                                                              HRIF_WayPoint2
                                                                                                                                                              HRIF_SetScriptForceControlState
                                                                                                                                                              HRIF_MoveS                                                                                                  
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* V1.0.5.0                          2024.09.02                                               HRIF_MovePathJOL
                                                                                             HRIF_GetMovePathJOLIndex
                                                                                             HRIF_cdsSetIO
                                                                                             HRIF_SetPoseTrackingStopTimeOut
                                                                                             HRIF_EnterSafeGuard
                                                                                             HRIF_AddSafePlane
                                                                                             HRIF_DelSafePlane
                                                                                             HRIF_ReadSafePlaneList
                                                                                             HRIF_ReadSafePlane
                                                                                             HRIF_UpdateSafePlane
                                                                                             HRIF_SetDepthThresholdForDampingArea
                                                                                             HRIF_SpeedJ
                                                                                             HRIF_SpeedL
                                                                                             HRIF_ReadTriStageSwicth
                                                                                             HRIF_SetTriStageSwicth                                                                          
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ 
* V1.0.5.1                          2024.10.10                                                                                                                HRIF_ReadCurFSM
                                                                                                                                                              HRIF_MoveLinearWeave
                                                                                                                                                              HRIF_MoveCircularWeave                                                                       
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ 
* V1.0.6.0                          2024.10.11                                               HRIF_SwitchScript
                                                                                             HRIF_ReadDefaultScript                                                                                                                                                                                                                                                                                                                  HRIF_InitPathJ(Delete)                                                                          
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ 
* V1.0.7.0                          2024.12.27                                               HRIF_MoveAlignToZ
                                                                                             HRIF_SetBaseInstallingAngle
                                                                                             HRIF_GetBaseInstallingAngle                                                                    
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ 
* V1.0.8.0                          2024.02.05                                               HRIF_SetLastCalibParams
                                                                                             HRIF_GetLastCalibParams                                                       
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ 
* V1.0.9.0                          2025.03.05                                               HRIF_GetLoadIdentifyResult
                                                                                             HRIF_LoadIdentify
                                                                                             HRIF_SetFTCalibration
                                                                                             HRIF_ReadForceData
                                                                                             HRIF_SetInitializeForceSensor
                                                                                             HRIF_GetLastCalibParams  
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ 
* V1.0.10.0                          2025.03.25                                              HRIF_ShortJogJ
                                                                                             HRIF_ShortJogL
                                                                                             HRIF_LongJogJ
                                                                                             HRIF_LongJogL
                                                                                             HRIF_LongMoveEvent     
* V1.0.11.0                          2025.07.30                                              HRIF_GetInverseDynamics
                                                                                             HRIF_SetFTUCS
                                                                                             HRIF_ReadFTUCS                                                                                                                                                                                                                                                        
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ 
* V1.0.12.0                          2025.08.13                                              HRIF_ReadAllBoxCI
                                                                                             HRIF_ReadAllBoxCO
                                                                                             HRIF_ReadAllBoxDI
                                                                                             HRIF_ReadAllBoxDO
                                                                                             HRIF_ReadActCoord
                                                                                             HRIF_ReadActCoord_nJ
                                                                                             HRIF_CalTCPOrt
                                                                                             HRIF_SetDftTCP
                                                                                             HRIF_SetPathRefJoints
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* V1.1.0.0                           2025.09.12                                                                                                                Modify connection
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* V1.1.0.1                          2025.11.04                                               Bilingual Annotations                                                                
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* V1.1.1.0                          2025.11.24                                               HRIF_SetIOBeforeTarget
* ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 '''


import time
from tokenize import Double
import socket
import os
import struct
from enum import IntEnum


# from yaml import compose_all


class RbtFSM(IntEnum):
    enCPSState_PreInitialize = 0  # PreInitialize 
    enCPSState_Initialize = 1  # 1 Initialize 
    # ElectricBox FSM 
    enCPSState_ElectricBoxDisconnect = 2  # 2 ElectricBoxDisconnect  
    enCPSState_ElectricBoxConnecting = 3  # 3 ElectricBoxConnecting  
    enCPSState_EmergencyStopHandling = 4  # 4 EmergencyStopHandling  
    enCPSState_EmergencyStop = 5  # 5 EmergencyStop  
    enCPSState_Blackouting48V = 6  # 6 Blackouting48V  
    enCPSState_Blackout48V = 7  # 7 Blackout48V 
    enCPSState_Electrifying48V = 8  # 8 Electrifying48V  
    enCPSState_SafetyGuardErrorHandling = 9  # 9 SafetyGuardErrorHandling 
    enCPSState_SafetyGuardError = 10  # 10 SafetyGuardError
    enCPSState_SafetyGuardHandling = 11  # 11 SafetyGuardHandling  
    enCPSState_SafetyGuard = 12  # 12 SafetyGuard  
    # controller FSM  
    enCPSState_ControllerDisconnecting = 13  # 13 ControllerDisconnecting  
    enCPSState_ControllerDisconnect = 14  # 14 ControllerDisconnect 
    enCPSState_ControllerConnecting = 15  # 15 ControllerConnecting 
    enCPSState_ControllerVersionError = 16  # 16 ControllerVersionError  
    enCPSState_EtherCATError = 17  # 17 EtherCATError
    enCPSState_ControllerChecking = 18  # 18 ControllerChecking 
    # Robot FSM 
    enCPSState_Reseting = 19  # 19 Reseting 
    enCPSState_RobotOutofSafeSpace = 20  # 20 RobotOutofSafeSpace 
    enCPSState_RobotCollisionStop = 21  # 21 RobotCollisionStop 
    enCPSState_Error = 22  # 22 Error 
    enCPSState_Enabling = 23  # 23 Enabling 
    enCPSState_Disable = 24  # 24 Disable 
    enCPSState_Moving = 25  # 25 Moving 
    enCPSState_LongJogMoving = 26  # 26 LongJogMoving 
    enCPSState_RobotStopping = 27  # 27 RobotStopping 
    enCPSState_Disabling = 28  # 28 Disabling 
    enCPSState_RobotOpeningFreeDriver = 29  # 29 RobotOpeningFreeDriver 
    enCPSState_RobotClosingFreeDriver = 30  # 30 RobotClosingFreeDriver 
    enCPSState_FreeDriver = 31  # 31 FreeDriver 
    enCPSState_RobotHolding = 32  # 32 RobotHolding 
    enCPSState_StandBy = 33  # 33 StandBy 
    # script FSM 
    enCPSState_ScriptRunning = 34  # 34 ScriptRunning 
    enCPSState_ScriptHoldHandling = 35  # 35 ScriptHoldHandling 
    enCPSState_ScriptHolding = 36  # 36 ScriptHolding 
    enCPSState_ScriptStopping = 37  # 37 ScriptStopping 
    enCPSState_ScriptStopped = 38  # 38 ScriptStopped 
    # HRApp 
    enCPSState_HRAppDisconnected = 39  # 39 HRAppDisconnected 
    enCPSState_HRAppError = 40  # 40 HRAppError
    # RobotLoadIdentify 
    enCPSState_RobotLoadIdentify = 41  # 41 RobotLoadIdentify 
    # brake 
    enCPSState_Braking = 42  # 42 Braking 
    enCPSState_TemperatureTooLow = 43  # 43 TemperatureTooLow 
    # FT 
    enCPSState_FTOpeningFreeDriver = 44  # 44 FTOpeningFreeDriver 
    enCPSState_FTClosingFreeDriver = 45  # 45 FTClosingFreeDriver 
    enCPSState_FTFreeDriver = 46  # 46 FTFreeDriver 


dic_ErrorCode = {
    39500: "NotConnected",
    39501: "ParamErrorInCommand",
    39502: "ParamErrorInResponse",
    39503: "SocketCommError",
    39504: "Connect2CPSFailed",
    39505: "CmdErrorInResponse",
    20018: ""
}

import threading

lock = threading.Lock()
lock_fast = threading.Lock()


class RbtClient(object):
    clientIP = '127.0.0.1'
    clientPort = 10003
    output_log = False

    def __init__(self):
        self.fast_cmd_list = []
        self.hb_thread = None
        self.tcp = None
        self.tcp_fast = None
        self.fast_port = None
        self.lock = threading.Lock()
        self.lock_fast = threading.Lock()
        self.stop_heartbeat = False

    def _send_and_recv(self, tcp_socket, cmd, timeout=10):
        """General send and receive methods for handling data transmission, including timeout control."""
        tcp_socket.send(cmd.encode())
        count = 0
        ret = ""
        tcp_socket.settimeout(timeout)
        while count < 5:
            count += 1
            try:
                data = tcp_socket.recv(4096).decode("utf-8", "ignore")
                if self.output_log:
                    print(data)
                if data:
                    ret += data
                    if ret.endswith(';'):
                        break
            except socket.timeout:
                continue  # Time Retry
        else:
            # data recceive timeout 
            raise TimeoutError("data recceive timeout.")
        return ret

    def heartbeat_thread(self):
        """Heartbeat thread, regularly check connection status"""
        result = []
        while not self.stop_heartbeat:
            nRet = self.sendAndRecv('IsSimulation,;', result)
            if nRet != 0:
                self.DisconnectFromCPS()
                break
            time.sleep(1)

    def Connect2CPS(self, hostName, nPort):
        """Connect to CPS and start the heartbeat thread, set the connection parameters."""
        self.clientIP = hostName
        self.clientPort = nPort

        # create TCP connection 
        self.tcp = socket.socket()
        self.tcp.settimeout(5)
        ret = self.tcp.connect_ex((self.clientIP, self.clientPort))

        if ret != 0:
            self.tcp.close()
            print(f"connect error [error is {ret}.msg:{os.strerror(ret)}]")
            return ret

        # Start heartbeat thread (if not start) 
        if not self.hb_thread:
            self.stop_heartbeat = False
            self.hb_thread = threading.Thread(target=self.heartbeat_thread, daemon=True)
            self.hb_thread.start()

        # Get fastport 
        result = []
        nRet = self.sendAndRecv('ReadFastCmdPort,0,;', result)
        if nRet != 0:
            return ret

        self.fast_port = int(result[0])
        # Is the current connection a fastport 
        if self.fast_port == self.clientPort:  
            return 0

        # Connect to fastport 
        self.tcp_fast = socket.socket()
        self.tcp_fast.settimeout(5)
        ret = self.tcp_fast.connect_ex((self.clientIP, self.fast_port))

        self.sendAndRecv_fast('ReadCmdList,0,;', self.fast_cmd_list)

        return ret

    def DisconnectFromCPS(self):
        """Disconnect and stop the heartbeat thread."""
        # End heartbeat thread using flag bit 
        self.stop_heartbeat = True  

        if self.tcp:
            self.tcp.close()
            self.tcp = None

        if self.tcp_fast:
            self.tcp_fast.close()
            self.tcp_fast = None

        return 0

    def sendScriptFinish(self, errorCode):
        """"Send script completion information."""
        command = f'SendScriptFinish,0,{errorCode},;'
        self.tcp.send(command.encode())
        self.tcp.recv(self.clientPort).decode("utf-8", "ignore")

    def setOutputLog(self, output):
        """"Set output log flag """
        self.output_log = output

    def sendAndRecv_fast(self, cmd, result):
        """Send and Receive(via fast port)."""
        with self.lock_fast:
            try:
                ret = self._send_and_recv(self.tcp_fast, cmd)
                retData_fast = ret.split(',')
                if len(retData_fast) < 3 or retData_fast[0] == "errorcmd":
                    return 39503

                if retData_fast[1] == "Fail":
                    errorData = int(retData_fast[2])
                    return errorData

                if cmd.split(",")[0] != retData_fast[0]:
                    return 39505

                result.clear()
                result.extend(retData_fast[2:-1])  # Ignore the first two elements and the last element 
            except Exception as e:
                print(f"Exception:{e}")
                return 39503
        return 0

    def sendAndRecv(self, cmd, result):
        """Send and Recevie(via standard port)"""
        if cmd.split(",")[0] in self.fast_cmd_list:
            return self.sendAndRecv_fast(cmd,result)
        with self.lock:
            try:
                ret = self._send_and_recv(self.tcp, cmd)
                retData = ret.split(',')
                if len(retData) < 3 or retData[0] == "errorcmd":
                    return 39503

                if retData[1] == "Fail":
                    errorData = int(retData[2])
                    return errorData

                if cmd.split(",")[0] != retData[0]:
                    return 39505

                result.clear()
                result.extend(retData[2:-1])  # Ignore the first two elements and the last element 
            except Exception as e:
                print(f"Exception: {e}")
                return 39503
        return 0

class PluginClient(object):
    # for v8 plugin
    clientIP = '127.0.0.1'
    clientPort = 40005
    plugin_lock = threading.Lock()

    def __init__(self):
        self.tcp = None

    def Connect2Plugin(self, hostName):
        self.clientIP = hostName
        self.tcp = socket.socket()
        self.tcp.settimeout(2)
        ret = self.tcp.connect_ex((self.clientIP, self.clientPort))

        if ret != 0:
            self.tcp.close()
            print("connect error [error is {0}.msg:{1}]".format(ret, os.strerror(ret)))
            return ret

        return ret

    def DisconnectFromPlugin(self):
        self.tcp.close()
        self.tcp = None
        return 0

    def sendAndRecv(self, cmd, result):
        try:
            with self.plugin_lock:
                self.tcp.send(cmd.encode())
                count = 0
                ret = ""
                self.tcp.settimeout(10)  # Set the receive timeout to 10 seconds and attempt to receive 6 times 
                while count < 6:
                    count += 1
                    try:
                        data = self.tcp.recv(4096).decode("utf-8", "ignore")
                        if data:
                            ret += data
                            if ret.endswith(';'):
                                break
                    except socket.timeout:
                        continue  # Time Retry
                else:
                    raise TimeoutError("receive data timeout")

            retData = ret.split(',')

            if retData[1] == "Fail":
                errorData = int(retData[2])
                return errorData

            # ensure result is a list 
            if not isinstance(result, list):
                raise TypeError("result should a list")

            if cmd.split(",")[0] != retData[0]:
                return 39505

            # Process returned data 
            result.clear()
            result.extend(retData[2:-1])  # Ignore the first two elements and the last element 

        except Exception as e:
            print("Exception:", e)
            return 39503
        return 0

class CPSClient(object):
    clientIP = '127.0.0.1'
    clientPort = 10003
    g_clients = []
    g_plugin_clients = []
    MaxBox = 5
    g_client_state = [False, False, False, False, False]
    g_plugin_client_state = [False, False, False, False, False]
    isV8CPS = False
    g_lock = threading.Lock()

    dic_FSM = {
        0: "PreInitialize",
        1: "Initialize",
        2: "ElectricBoxDisconnect",
        3: "ElectricBoxConnecting",
        4: "EmergencyStopHandling",
        5: "EmergencyStop",
        6: "Blackouting48V",
        7: "Blackout48V",
        8: "Electrifying48V",
        9: "SafetyGuardErrorHandling",
        10: "SafetyGuardError",
        11: "SafetyGuardHandling",
        12: "SafetyGuard",
        13: "ControllerDisconnecting",
        14: "ControllerDisconnect",
        15: "ControllerConnecting",
        16: "ControllerVersionError",
        17: "EtherCATError",
        18: "ControllerChecking",
        19: "Reseting",
        20: "RobotOutofSafeSpace",
        21: "RobotCollisionStop",
        22: "Error",
        23: "Enabling",
        24: "Disable",
        25: "Moving",
        26: "LongJogMoving",
        27: "RobotStopping",
        28: "Disabling",
        29: "RobotOpeningFreeDriver",
        30: "RobotClosingFreeDriver",
        31: "FreeDriver",
        32: "RobotHolding",
        33: "StandBy",
        34: "ScriptRunning",
        35: "ScriptHoldHandling",
        36: "ScriptHolding",
        37: "ScriptStopping",
        38: "ScriptStopped",
        39: "HRAppDisconnected",
        40: "HRAppError",
        41: "RobotLoadIdentify",
        42: "Braking",
        43: "TemperatureTooLow",
        44: "FTOpeningFreeDriver",
        45: "FTClosingFreeDriver",
        46: "FTFreeDriver"
    }

    def __init__(self):
        with self.g_lock:
            if len(self.g_clients) == self.MaxBox:
                return
            for i in range(self.MaxBox):
                self.g_clients.append(RbtClient())
                self.g_plugin_clients.append(PluginClient())
            return

    def _waitMotion(self, isblending):
        motionIndex = 0
        doneFlag = '0'
        movingFlag = '1'
        if isblending:
            motionIndex = 11
            doneFlag = '1'
            movingFlag = '0'

        time.sleep(0.02)
        nDisableCNT = 0
        while True:
            if nDisableCNT >= 5:
                time.sleep(0.01)
                os._exit(0)
            ret = []
            self.HRIF_ReadRobotState(0, 0, ret)
            if ret[1] == '0':
                nDisableCNT += 1
                log = ('[script]EnableState[' + ret[2] + '],count[' + str(nDisableCNT) + '] error')
                continue
            else:
                nDisableCNT = 0

            if ret[2] == '1' or ret[7] == '1' or ret[9] == '0' or ret[10] == '0':
                log = ('[script]errorState[' + ret[2] + '],emergency[' + ret[7] + '],Electfify[' + ret[9] + ']')
                # print(log)
                time.sleep(0.1)
                os._exit(0)
            elif ret[8] == '1':
                time.sleep(0.01)
                continue

            elif ret[6] == '1':
                time.sleep(0.01)
                continue

            elif ret[motionIndex] == doneFlag:
                log = ('[script]ret[' + str(motionIndex) + ']==' + ret[motionIndex])
                # print(log)
                break

            elif ret[motionIndex] == movingFlag:
                log = ('ret[' + str(motionIndex) + ']==' + ret[motionIndex])
                time.sleep(0.01)
                continue

            else:
                log = '[script]waitBlendingDone unknow status exit'
                # print(log)
                os._exit(0)
        return

    def waitMoveDone(self, boxID, rbtID):
        self._waitMotion(False)

    def waitBlendingDone(self, boxID, rbtID):
        self._waitMotion(True)

    def waitFSM(self, targetFSM, wait_timeout):
        result = []
        self.HRIF_ReadCurFSM(0, 0, result)
        start = time.perf_counter()
        end = time.perf_counter()
        if not result:
            return -1
        while int(result[0]) != targetFSM:
            end = time.perf_counter()
            if (end - start) >= wait_timeout:
                break
            time.sleep(0.1)
            self.HRIF_ReadCurFSM(0, 0, result)
        return int(result[0])

    def HRIF_FinishInitialize(self):
        result = []
        command = 'FinishInitialize,;'
        return self.g_clients[0].sendAndRecv(command, result)

    def HRIF_SetOutputLog(self, output):
        self.g_clients[0].setOutputLog(output)

    def HRIF_ReadFastCmdPort(self, result):
        command = 'ReadFastCmdPort,0,;'
        return self.g_clients[0].sendAndRecv(command, result)

    def HRIF_ReadCmdList(self, result):
        command = 'ReadCmdList,0,;'
        return self.g_clients[0].sendAndRecv_fast(command, result)

    def IsHRAppCmdExist(self):
        result = []
        command = 'IsHRAppCmdExist,0,;'
        return self.g_clients[0].sendAndRecv(command, result)

    #
    # part 1 Interfaces for initialization
    #

    '''
    *	@index : 1
    *	@param brief: Connect to the robot server
    *	@param boxID: Control box ID
    *   @param hostName : IP address of CPS
    *	@param nPort : Port number
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_Connect(self, boxID, hostName, nPort):
        if boxID >= self.MaxBox:
            return 39501
        try:
            ret = self.g_clients[boxID].Connect2CPS(hostName, nPort)
            if ret != 0:
                return 39504
            self.g_client_state[boxID] = True

            ret = self.IsHRAppCmdExist()
            if ret != 0:
                return 0
            self.isV8CPS = True
            plugin_ret = self.g_plugin_clients[boxID].Connect2Plugin(hostName)

            if plugin_ret == 0:
                self.g_plugin_client_state[boxID] = True
            else:
                print("Connect to plugin server failed!")
            return 0
        except:
            return 39504

    '''
    *	@index : 2
    *	@param brief:Disconnet from robot server
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_DisConnect(self, boxID):
        if boxID >= self.MaxBox:
            return 39501
        try:
            self.g_clients[boxID].DisconnectFromCPS()
            self.g_client_state[boxID] = False
            if self.isV8CPS:
                self.g_plugin_clients[boxID].DisconnectFromPlugin()
                self.g_plugin_client_state[boxID] = False
            return 0
        except:
            return 39504

    '''
    *	@index : 3
    *	@param brief: Check the connection status to CPS
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_IsConnected(self, boxID):
        return self.g_client_state[boxID]

    '''
    *	@index : 4
    *	@param brief: Power off the robot and shut down the system
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ShutdownRobot(self, boxID):
        result = []
        command = 'OSCmd,1,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Connect to control box
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_Connect2Box(self, boxID):
        result = []
        command = 'ConnectToBox,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Power on the robot
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_Electrify(self, boxID):
        result = []
        command = 'Electrify,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Power off the robot
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_BlackOut(self, boxID):
        result = []
        command = 'BlackOut,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 8
    *	@param brief: Connect to the controller, start master, initialize slave, configure and check paramters, finally switch to DISABLE state
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_Connect2Controller(self, boxID):
        result = []
        command = 'StartMaster,'
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 9
    *	@param brief: Check the simulation status
    *	@param boxID: Control box ID
    *	@param state: status
    *                     0:real mode
    *                     1:simulated mode
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetSimulation(self, boxID, state):
        result = []
        command = 'SetSimulation,0,'
        command += str(state)
        command += ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 10
    *	@param brief: Check the simulation status
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: status
    *                        0:real mode
    *                        1:simulated mode
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_IsSimulateRobot(self, boxID, result):
        command = 'IsSimulation,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 11
    *	@param brief: Check the controller's state
    *	@param boxID: Control box ID
    *	@param result[0]: Start status
    *	                     0 : not started
    *                        1 : started
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_IsControllerStarted(self, boxID, result):
        command = 'ReadControllerState,'
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Get explanation of error code
    *	@param boxID: Control box ID
    *	@param nErrorCode: Error code
    *	@param result[0]: Error code explanation
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetErrorCodeStr(self, boxID, nErrorCode, result):
        command = 'GetErrorCodeStr,'
        command += str(nErrorCode) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 13
    *	@param brief: Read the version of robot
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: Whole version
    *	@param result[1]: CPS version 
    *	@param result[2]: Controller version
    *	@param result[3]: Control box version
    *	@param result[4]: Firmware version of control board
    *	@param result[5]: Firmware version of control board
    *	@param result[6]: Algorithm version
    *	@param result[7]: Firmware version
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadVersion(self, boxID, rbtID, result):
        command = 'ReadVersion,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 14
    *	@param brief: Read the robot model
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: Robot model
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadRobotModel(self, boxID, rbtID, result):
        command = 'ReadRobotModel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 2 Interfaces for axis group control command
    #

    '''
    *	@index : 1
    *	@param brief:  Enable the robot
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GrpEnable(self, boxID, rbtID):
        result = []
        command = 'GrpPowerOn,'
        command += str(rbtID) + ',;'
        ret = self.g_clients[boxID].sendAndRecv(command, result)
        if ret == 20005:
            command = 'GrpEnable,'
            command += str(rbtID) + ',;'
            ret = self.g_clients[boxID].sendAndRecv(command, result)
        return ret


    '''
    *	@index : 2
    *	@param brief: Disable the robot
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GrpDisable(self, boxID, rbtID):
        result = []
        command = 'GrpPowerOff,'
        command += str(rbtID) + ',;'
        ret = self.g_clients[boxID].sendAndRecv(command, result)
        if ret == 20005:
            command = 'GrpDisable,'
            command += str(rbtID) + ',;'
            ret = self.g_clients[boxID].sendAndRecv(command, result)
        return ret

    '''
    *	@index : 3
    *	@param brief: Reset the robot
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_GrpReset(self, boxID, rbtID):
        result = []
        command = 'GrpReset,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Stop robot moving
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GrpStop(self, boxID, rbtID):
        result = []
        command = 'GrpStop,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Pause robot moving
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GrpInterrupt(self, boxID, rbtID):
        result = []
        command = 'GrpInterrupt,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Continue robot moving after pause
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GrpContinue(self, boxID, rbtID):
        result = []
        command = 'GrpContinue,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Close free driver
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_GrpCloseFreeDriver(self, boxID, rbtID):
        result = []
        command = 'GrpCloseFreeDriver,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 8
    *	@param brief: Open free driver
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GrpOpenFreeDriver(self, boxID, rbtID):
        result = []
        command = 'GrpOpenFreeDriver,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 9
    *	@param brief: Open the brake
    *	@param boxID: Control box ID
    *	@param nAxisID : Robot Axis ID, 0-5
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    *	@param nAxisID[0]: Axis id 
    '''
    def HRIF_OpenBrake(self, boxID, nAxisID):
        result = []
        command = 'OpenBrake,0,'
        command += str(nAxisID)
        command += ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 10
    *	@param brief: Close the brake
    *	@param boxID: Control box ID
    *	@param nAxisID : Robot Axis ID, 0-5
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    *	@param nAxisID[0]: Axis id
    '''
    def HRIF_CloseBrake(self, boxID, nAxisID):
        result = []
        command = 'CloseBrake,0,'
        command += str(nAxisID)
        command += ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 11
    *	@param brief: Read the brake status of each Axis
    *	@param boxID: Control box ID
    *	@param result[0]~result[5] : Robot Axis status
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadBrakeStatus(self, boxID, result):
        command = 'ReadBrakeStatus,0,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Move to safe space
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveToSS(self, boxID):
        result = []
        command = 'MoveToSS,0,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 13
    *	@param brief:Enter or exit safeguard status by force to realize soft EStop(emergency stop). Move will be stopped. System can be reset after EStop is canceled.
    *	@param boxID: Control box ID
    *	@param rbtID : Robot ID
    *	@param flag: 1 to enter, 0 to cancel
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_EnterSafeGuard(self, boxID, rbtID, flag):
        result = []
        command = 'EnterSafetyGuard,'
        command += str(rbtID) + ','
        command += str(flag) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 14
    *	@param brief: Read whether the three-stage switch is turned on and the mode
    *	@param boxID: Control box ID
    *	@param rbtID : Robot ID
    *	@param result[0]: Three stage switch 
    *                                                        0:colse
    *                                                        1:open
    *	@param result[0]: Mode
    *                                                        0:FreeDrive
    *                                                        1:Enable
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadTriStageSwitch(self, boxID, rbtID, result):
        command = 'ReadTriStageSwitch,'
        command += str(rbtID) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 15
    *	@param brief: Set three-stage switch and mode
    *	@param boxID: Control box ID
    *	@param rbtID : Robot ID
    *	@param enable : Three stage switch 
    *                                                              0:colse
    *                                                              1:open
    *   @param mode : Mode
    *                                                              0:FreeDrive
    *                                                              1:Enable
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetTriStageSwitch(self, boxID, rbtID, enable, mode):
        result = []
        command = 'SetTriStageSwitch,'
        command += str(rbtID) + ','
        command += str(enable) + ','
        command += str(mode) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 16
    *	@param brief: Z-axis alignment
    *	@param boxID : Control box ID
    *	@param rbtID : Robot ID
    *	@param tcp : Tcp Name 
    *   @param ucs : Ucs Name
    *   @param result[0] : Is the Z-axis aligned 
    *   @param result[1]-result[6] : J1-J6 Joint Position 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveAlignToZ(self, boxID, rbtID, tcp, ucs, result):
        command = 'MoveAlignToZ,'
        command += str(rbtID) + ','
        command += str(tcp) + ','
        command += str(ucs) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 17
    *	@param brief: Start Load Identification.
    *	@param boxID : Control box ID
    *	@param rbtID : Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_LoadIdentify(self, boxID, rbtID):
        result = []
        command = 'LoadIdentify,'
        command += str(rbtID) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 18
    *	@param brief: Get the load identification result
    *	@param boxID : Control box ID
    *	@param rbtID : Robot ID
    *   @param result[0] : Load identification status:
    *                    - 0: Success
    *                    - 1: First trajectory error
    *                    - 2: Second trajectory error
    *                    - 3: Third trajectory error
    *                    - 4: Load identification in progress
    *                    - 5: Unexpected stop
    *                    - 6: Unexpected exit
    *                    - 7: Initialization, load identification not started
    *   @param result[1]: Progress status (0~100)(Current load identification progress)
    *                 
    *   @param result[2] : Identified load mass (unit: kg)
    *   @param result[3] :Load center of mass X coordinate
    *   @param result[4] :Load center of mass Y coordinate
    *   @param result[5] : Load center of mass Z coordinate
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetLoadIdentifyResult(self, boxID, rbtID, result):
        command = 'GetLoadIdentifyResult,'
        command += str(rbtID) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 3 Interfaces for script
    #

    '''
    *	@index : 1
    *	@param brief: Run the specified function
    *	@param boxID: Control box ID
    *	@param strFuncName : The specified function name composed in the teaching pendant
    *	@param param : Parameters
    *	@param result[0] : Function Name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_RunFunc(self, boxID, funcName, params, result):
        command = 'RunFunc,'
        command += funcName + ','
        for param in params:
            command += str(param) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Run the main function to start the script execution composed and compiled in the teaching pendant
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_StartScript(self, boxID):
        result = []
        command = 'StartScript,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Stop the script execution running in teaching pendant
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_StopScript(self, boxID):
        result = []
        command = 'StopScript,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Pause the script execution running in teaching pendant
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PauseScript(self, boxID):
        result = []
        command = 'PauseScript,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Continue the script execution paused int the teaching pendant
    *	@param boxID: Control box ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ContinueScript(self, boxID):
        result = []
        command = 'ContinueScript,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Applies the specified script file
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param name: ScriptName
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SwitchScript(self, boxID, rbtID, name):
        result = []
        command = 'SwitchScript,'
        command += str(rbtID) + ','
        command += name +',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Read the current application script file
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: ScriptName
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadDefaultScript(self, boxID, rbtID, result):
        command = 'ReadDefaultScript,'
        command += str(rbtID) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 4  Interfaces for control box
    #

    '''
    *	@index : 1
    *	@param brief: Read box message
    *	@param boxID: Control box ID
    *	@param result[0] : Control box connection status
    *	@param result[1] : Voltage value with 48V
    *	@param result[2] : 48V output voltage
    *	@param result[3] : 48V output current
    *	@param result[4] : Remote emergency stop status
    *	@param result[5] : Three stage status
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadBoxInfo(self, boxID, result):
        command = 'ReadBoxInfo,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index: 2  Read box control input
    *	@param boxID: Control box ID
    *	@param bit: CI bit
    *	@param result[0]: CI value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadBoxCI(self, boxID, bit, result):
        command = 'ReadBoxCI,' + str(bit) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Read box digital input
    *	@param boxID: Control box ID
    *	@param bit : DI bit
    *	@param result[0]: DI value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadBoxDI(self, boxID, bit, result):
        command = 'ReadBoxDI,' + str(bit) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Read box control output
    *	@param boxID: Control box ID
    *	@param bit : CO bit
    *	@param result[0]: CO valur
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadBoxCO(self, boxID, bit, result):
        command = 'ReadBoxCO,' + str(bit) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Read box digital output
    *	@param boxID: Control box ID
    *	@param bit : DO bit
    *	@param result[0]: DO value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadBoxDO(self, boxID, bit, result):
        command = 'ReadBoxDO,' + str(bit) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Read all control box config digital input statuses
    *	@param boxID: Control box ID
    *	@param result[0]-result[5]: Vector storing all config input (CI) values
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadAllBoxCI(self, boxID,result):
        command = 'ReadBoxCI,'
        for i in range(8):
            command += str(i) +','
        command += ';'
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Read all control box config digital input statuses
    *	@param boxID: Control box ID
    *	@param result[0]-result[5]: Vector storing all digital input (DI) values
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''  
    def HRIF_ReadAllBoxDI(self, boxID,result):
        command = 'ReadBoxDI,'
        for i in range(8):
            command += str(i) +','
        command += ';'
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 8
    *	@param brief: Read all control box config digital output statuses
    *	@param boxID: Control box ID
    *	@param result[0]-result[5]: Vector storing all config output (CO) values
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadAllBoxCO(self, boxID,result):
        command = 'ReadBoxCO,'
        for i in range(8):
            command += str(i) +','
        command += ';'
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 9
    *	@param brief: Read all control box general digital output statuses
    *	@param boxID: Control box ID
    *	@param result[0]-result[5]: Vector storing all digital output (DO) values
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadAllBoxDO(self, boxID,result):
        command = 'ReadBoxDO,'
        for i in range(8):
            command += str(i) +','
        command += ';'
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 10
    *	@param brief: Read box analog input
    *	@param boxID: Control box ID
    *	@param bit : AI bit
    *	@param result[0] : Current (4~20mA) or voltage (0~10V)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadBoxAI(self, boxID, bit, result):
        command = 'ReadBoxAI,' + str(bit) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 11
    *	@param brief: Read box analog output
    *	@param boxID: Control box ID
    *	@param bit : AO bit
    *	@param result[0] : Current or voltage mode
    *	@param result[1] :  Current value (4~20mA) or voltage value (0~10V)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadBoxAO(self, boxID, bit, result):
        command = 'ReadBoxAO,' + str(bit) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Set Box control output
    *	@param boxID: Control box ID
    *	@param bit : CO bit
    *	@param state : CO value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetBoxCO(self, boxID, bit, state):
        result = []
        command = 'SetBoxCO,' + str(bit) + ',' + str(state) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 13
    *	@param brief: Set Box digital output
    *	@param boxID: Control box ID
    *	@param bit : DO
    *	@param state :  DO value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetBoxDO(self, boxID, bit, state):
        result = []
        command = 'SetBoxDO,' + str(bit) + ',' + str(state) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 14
    *	@param brief: Set Box analog output mode
    *	@param boxID: Control box ID
    *	@param bit : AO bit
    *	@param pattern : AO Mode
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetBoxAOMode(self, boxID, index, pattern):
        result = []
        command = 'SetBoxAOMode,' + str(index) + ',' + str(pattern) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 15
    *	@param brief:Set Box analog output and mode
    *	@param boxID: Control box ID
    *	@param bit : AO bit
    *	@param value : AO value
    *	@param pattern : AO mode
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetBoxAOVal(self, boxID, index, value, pattern):
        result = []
        command = 'SetBoxAO,' + str(index) + ',' + str(value) + ',' + str(pattern) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 16
    *	@param brief: Set End digital output
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param bit : End DO bit
    *	@param state : End DO value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetEndDO(self, boxID, rbtID, bit, state):
        result = []
        command = 'SetEndDO,'
        command += str(rbtID) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 17
    *	@param brief: Set welding analog output voltage
    *	@param boxID: Control box ID
    *	@param nState : Channel switch status
    *	@param nIndex : Voltage analog channel
    *	@param dInitAO : Initial voltage
    *	@param dWeldingAO : Welding voltage
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMoveParamsAO(self, boxID, nState, nIndex, dInitAO, dWeldingAO):
        result = []
        command = 'SetMoveParamsAO,0,'
        command += str(nState) + ','
        command += str(nIndex) + ','
        command += str(dInitAO) + ','
        command += str(dWeldingAO) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 18
    *	@param brief: Read End digital input
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param bit :  End DI bit
    *	@param result[0] : End DI value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadEndDI(self, boxID, rbtID, bit, result):
        command = 'ReadEI,'
        command += str(rbtID) + ','
        command += str(bit) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 19
    *	@param brief: Read End digital output
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param bit : End DO bit
    *	@param result[0] : End DO value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadEndDO(self, boxID, rbtID, bit, result):
        command = 'ReadEO,'
        command += str(rbtID) + ','
        command += str(bit) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 20
    *	@param brief: Read End analog input
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param bit : End AI bit
    *	@param result[0] : End AI value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadEndAI(self, boxID, rbtID, bit, result):
        command = 'ReadEAI,'
        command += str(rbtID) + ','
        command += str(bit) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 21
    *	@param brief: Read End Button
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0] : End button 1
    *	@param result[1] : End button 2
    *	@param result[2] : End button 3
    *	@param result[3] : End button 4
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadEndBTN(self, boxID, rbtID, result):
        command = 'ReadEndBTN,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 22
    *	@param brief: Set End Button
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param state : End button status, 1 for enabled, 0 for enabled
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_EnableEndBTN(self, boxID, rbtID, state):
        result = []
        command = 'EnableEndBTN,'
        command += str(rbtID) + ','
        command += str(state) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Set IO before the motion command reaches the target point
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nEndDOMask : The EndDO to be modified is identified by bit
    *   @param nEndDOVal :  The target state of each EndDO to be modified
    *   @param nBoxDOMask : The BoxDO to be modified is identified by bit
    *   @param nBoxDOVal : The target state of each BoxDO to be modified
    *   @param nBoxCOMask : The BoxCO to be modified is identified by bit
    *   @param nBoxCOVal : The target state of each BoxCO to be modified
    *   @param nBoxAOCH0_Mask : Indicator of whether BoxAOCH0 needs to be modified
    *   @param nBoxAOCH0_Mode :  Mode
    *   @param nBoxAOCH1_Mask :  Indicator of whether BoxAOCH1 needs to be modified
    *   @param nBoxAOCH1_Mode : Mode
    *   @param dbBoxAOCH0_Val :  Corresponding analog value
    *   @param dbBoxAOCH1_Val :  Corresponding analog value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_cdsSetIO(self, boxID, rbtID, nEndDOMask, nEndDOVal, nBoxDOMask, nBoxDOVal, nBoxCOMask, nBoxCOVal, nBoxAOCH0_Mask,
                nBoxAOCH0_Mode, nBoxAOCH1_Mask, nBoxAOCH1_Mode, dbBoxAOCH0_Val, dbBoxAOCH1_Val):
        result = []
        command = 'cdsSetIO,'
        command += str(nEndDOMask) + ','
        command += str(nEndDOVal) + ','
        command += str(nBoxDOMask) + ','
        command += str(nBoxDOVal) + ','
        command += str(nBoxCOMask) + ','
        command += str(nBoxCOVal) + ','
        command += str(nBoxAOCH0_Mask) + ','
        command += str(nBoxAOCH0_Mode) + ','
        command += str(nBoxAOCH1_Mask) + ','
        command += str(nBoxAOCH1_Mode) + ','
        command += str(dbBoxAOCH0_Val) + ','
        command += str(dbBoxAOCH1_Val) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
            *	@index : 24
            *	@param brief: Set IO before the motion command reaches the target point
            *	@param boxID: Control box ID
            *	@param rbtID: Robot ID
            *	@param nEndDOMask : The EndDO to be modified is identified by bit.
            *   @param nEndDOVal :  The target state of each EndDO to be modified.
            *   @param nBoxDOMask : The BoxDO to be modified is identified by bit.
            *   @param nBoxDOVal : The target state of each BoxDO to be modified.
            *   @param nBoxCOMask : The BoxCO to be modified is identified by bit.
            *   @param nBoxCOVal : The target state of each BoxCO to be modified.
            *   @param nBoxAOCH0_Mask : Indicator of whether BoxAOCH0 needs to be modified.
            *   @param nBoxAOCH0_Mode :  Mode
            *   @param nBoxAOCH1_Mask :  Indicator of whether BoxAOCH1 needs to be modified.
            *   @param nBoxAOCH1_Mode : Mode
            *   @param dbBoxAOCH0_Val :  Corresponding analog value
            *   @param dbBoxAOCH1_Val :  Corresponding analog value
            *   @param nMode :  Corresponding analog value / Mode: 0 (remaining time mode)  1 (remaining trajectory length mode)
            *   @param nRemainTimeOrDist :  Advance time or distance
            *	
            *	@return : nRet=0 : Function call succeeded
            *             nRet>0 : Error code of function call
            '''

    def HRIF_SetIOBeforeTarget(self, boxID, rbtID, nEndDOMask, nEndDOVal, nBoxDOMask, nBoxDOVal, nBoxCOMask, nBoxCOVal,
                               nBoxAOCH0_Mask, nBoxAOCH0_Mode, nBoxAOCH1_Mask, nBoxAOCH1_Mode, dbBoxAOCH0_Val,
                               dbBoxAOCH1_Val,
                               nMode, nRemainTimeOrDist):
        result = []
        command = 'SetIOBeforeTarget,'
        command += str(nEndDOMask) + ','
        command += str(nEndDOVal) + ','
        command += str(nBoxDOMask) + ','
        command += str(nBoxDOVal) + ','
        command += str(nBoxCOMask) + ','
        command += str(nBoxCOVal) + ','
        command += str(nBoxAOCH0_Mask) + ','
        command += str(nBoxAOCH0_Mode) + ','
        command += str(nBoxAOCH1_Mask) + ','
        command += str(nBoxAOCH1_Mode) + ','
        command += str(dbBoxAOCH0_Val) + ','
        command += str(dbBoxAOCH1_Val) + ','
        command += str(nMode) + ','
        command += str(nRemainTimeOrDist) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 5  Interfaces for read state and set command 
    #

    '''
    *	@index : 1
    *	@param brief: Set Override
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param vel: Override value (0.01~1.00)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetOverride(self, boxID, rbtID, vel):
        result = []
        command = 'SetOverride,'
        command += str(rbtID) + ','
        command += str(vel) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Set Tool motion
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param state: 0 for closed, 1 for open
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetToolMotion(self, boxID, rbtID, state):
        result = []
        command = 'SetToolMotion,'
        command += str(rbtID) + ','
        command += str(state) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Set payload
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param Mass:Mass
    *	@param Center_X: Gravity-CX
    *	@param Center_Y: Gravity-CY
    *	@param Center_Z: Gravity-CZ
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    ''' 
    def HRIF_SetPayload(self, boxID, rbtID, Mass, Center_X, Center_Y, Center_Z):
        result = []
        command = 'SetPayload,'
        command += str(rbtID) + ','
        command += str(Mass) + ','
        command += str(Center_X) + ','
        command += str(Center_Y) + ','
        command += str(Center_Z) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Set joint max velocity
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param Joint[0]-Joint[5]: Joint1~6 max velocity 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetJointMaxVel(self, boxID, rbtID, Joint):
        result = []
        command = 'SetJointMaxVel,'
        command += str(rbtID) + ','
        for i in range(len(Joint)):
            command += str(Joint[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 5
    *	@param brief: Set joint max velocity
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param Joint[0]-Joint[n-1]: Joint1~n max velocity 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetJointMaxVel_nJ(self, boxID, rbtID, Joint):
        result = []
        command = 'SetJointMaxVel,'
        command += str(rbtID) + ','
        for i in range(len(Joint)):
            command += str(Joint[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Set joint max acceleration
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param Joint[0]-Joint[5]: Joint1~6 max acceleration
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetJointMaxAcc(self, boxID, rbtID, Joint):
        result = []
        command = 'SetJointMaxAcc,'
        command += str(rbtID) + ','
        for i in range(len(Joint)):
            command += str(Joint[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 7
    *	@param brief: Set joint max acceleration
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param Joint[0]-Joint[n-1]: Joint1~n max acceleration 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetJointMaxAcc_nJ(self, boxID, rbtID, Joint):
        result = []
        command = 'SetJointMaxAcc,'
        command += str(rbtID) + ','
        for i in range(len(Joint)):
            command += str(Joint[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 8
    *	@param brief: Set linear max velocity
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param MaxVel: Linear max velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetLinearMaxVel(self, boxID, rbtID, MaxVel):
        result = []
        command = 'SetLinearMaxVel,'
        command += str(rbtID) + ','
        command += str(MaxVel) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 9
    *	@param brief:Set linear max acceleration
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param MaxAcc: Linear max acceleration
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetLinearMaxAcc(self, boxID, rbtID, MaxAcc):
        result = []
        command = 'SetLinearMaxAcc,'
        command += str(rbtID) + ','
        command += str(MaxAcc) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 10
    *	@param brief: Set max range of joint motion
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param pMax[0]-pMax[5]: Max joint angle
    *	@param pMin[0]-pMin[5]: Min joint angle
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMaxAcsRange(self, boxID, rbtID, pMax, pMin):
        result = []
        command = 'SetMaxAcsRange,'
        command += str(rbtID) + ','
        for i in range(len(pMax)):
            command += str(pMax[i]) + ','
        for i in range(len(pMin)):
            command += str(pMin[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 11
    *	@param brief: Set max range of joint motion
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param pMax[0]-pMax[n-1]: Max joint angle
    *	@param pMin[0]-pMin[n-1]: Min joint angle
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMaxAcsRange_nJ(self, boxID, rbtID, pMax, pMin):
        result = []
        command = 'SetMaxAcsRange,'
        command += str(rbtID) + ','
        for i in range(len(pMax)):
            command += str(pMax[i]) + ','
        for i in range(len(pMin)):
            command += str(pMin[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Set max range of linear motion
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param pMax:  Max range of XYZ 
    *	@param pMin:  Min range of XYZ
    *	@param pUcs:  UCS pose
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMaxPcsRange(self, boxID, rbtID, pMax, pMin, pUcs):
        result = []
        command = 'SetMaxPcsRange,'
        command += str(rbtID) + ','
        for i in range(3):
            command += str(pMax[i]) + ','
        command += str(180)
        command += ','
        command += str(180)
        command += ','
        command += str(180)
        command += ','
        for i in range(3):
            command += str(pMin[i]) + ','
        command += str(-180)
        command += ','
        command += str(-180)
        command += ','
        command += str(-180)
        command += ','
        for i in range(0, 6):
            command += str(pUcs[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 13
    *	@param brief: Read joint range and linear range
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: Max joint angle
    *	@param result[6]-result[11]: Min joint angle
    *	@param result[12]-result[17]: Max range of XYZRXRYRZ
    *	@param result[18]-result[23]: Min range of XYZRXRYRZ
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadMaxRange(self,  boxID, rbtID, result):
        command = 'ReadMaxRange,'
        command += str(rbtID) +','
        command += ';'
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 14
    *	@param brief: Read joint range and linear range
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]: Max joint angle
    *	@param result[n]-result[2n-1]: Min joint angle
    *	@param result[2n]-result[3n-1]: Max linear range
    *	@param result[3n]-result[4n-1]: Min linear range
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadMaxRange_nJ(self,  boxID, rbtID, result):
        command = 'ReadMaxRange,'
        command += str(rbtID) +','
        command += ';'
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 15
    *	@param brief: set the collision sensitivity level
    *	@param boxID: Control box ID
    *	@param nSafeLevel : sensitivity level, 0-5, 0 for the highest, 5 for the lowest
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetCollideLevel(self, boxID, nSafeLevel):
        result = []
        command = 'SetCollideLevel,0,' + str(nSafeLevel) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 16
    *	@param brief: Read the maximum payload
    *	@param boxID: Control box ID
    *	@param result : maximum payload at the end (kg)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadMaxPayload(self, boxID, result):
        command = 'ReadMaxPayload,0,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 17
    *	@param brief: Read payload
    *	@param boxID: Control box ID
    *	@param result[0]: Mass
    *	@param result[1]: Gravity-CX
    *	@param result[2]: Gravity-CY
    *	@param result[3]: Gravity-CZ
       *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadPayload(self, boxID, result):
        command = 'ReadPayload,0,;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 18
    *	@param brief: Read Override
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: Override value 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadOverride(self, boxID, rbtID, result):
        command = 'ReadOverride,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 19
    *	@param brief: Read joint max velocity
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: Max velocity of J1~J6
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadJointMaxVel(self, boxID, rbtID, result):
        command = 'ReadJointMaxVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 20
    *	@param brief: Read joint max velocity
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]: Max velocity of J1~Jn
    *	
    *	@return : nRet=0 : Function call succeeded
    *   
    '''
    def HRIF_ReadJointMaxVel_nJ(self, boxID, rbtID, result):
        command = 'ReadJointMaxVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 21
    *	@param brief: Read joint max acceleration
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5] : Max acceleration of J1~J6
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadJointMaxAcc(self, boxID, rbtID, result):
        command = 'ReadJointMaxAcc,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 22
    *	@param brief: Read joint max acceleration
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1] : Max acceleration of J1~Jn
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadJointMaxAcc_nJ(self, boxID, rbtID, result):
        command = 'ReadJointMaxAcc,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 23
    *	@param brief: Read joint max jerk
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5] : Max jerk of J1~J6
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadJointMaxJerk(self, boxID, rbtID, result):
        command = 'ReadJointMaxJerk,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 24
    *	@param brief: Read joint max jerk
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1] : Max jerk of J1~Jn
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadJointMaxJerk_nJ(self, boxID, rbtID, result):
        command = 'ReadJointMaxJerk,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 25
    *	@param brief: Read linear motion parameters
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0] : Linear motion velocity
    *	@param result[1] : Linear motion acceleration
    *	@param result[2] : Linear motion jerk
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_ReadLinearMaxSpeed(self, boxID, rbtID, result):
        command = 'ReadLinearMaxVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 26
    *	@param brief:Read Emergency stop information
    *	@param boxID: Control box ID
    *	@param result[0] : Error occurs when the two emergency signals are different
    *	@param result[1] : Cut off 48V output to the robot when an emergency stop occurs
    *	@param result[2] : Error occurs when the two safeguard signals are different
    *	@param result[3] : Stop the motion but never cutt off power supply when safeguard occurs
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_ReadEmergencyInfo(self, boxID, result):
        command = 'ReadEmergencyInfo,'
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 27
    *	@param brief: Read robot state
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0] : Moving state
    *   @param result[1] : Enable state
    *   @param result[2] : Error state
    *   @param result[3] : Error code
    *   @param result[4] : Error axis ID
    *   @param result[5] : Breaking status
    *   @param result[6] : Pause state
    *   @param result[7] : Emergency stop state
    *   @param result[8] : Safty guard state
    *   @param result[9] : Electrify state
    *   @param result[10] : Connection of control box state
    *   @param result[11] : Moving blending done state
    *   @param result[12] : In actual pose state
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_ReadRobotState(self, boxID, rbtID, result):
        command = 'ReadRobotState,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 28
    *	@param brief: Read current waypoint ID
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: Current ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCurWaypointID(self, boxID, rbtID, result):
        command = 'ReadCurWayPointID,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 29
    *	@param brief: Read axis error code
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param result[0]: Error code
    *	@param result[1]-result[5] : The error code of J1~J6, 0 if no error
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadAxisErrorCode(self, boxID, rbtID, result):
        command = 'ReadAxisErrorCode,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 30
    *	@param brief: Read axis error code
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param result[0]: Error code
    *	@param result[1]-result[n] : The error code of J1~Jn, 0 if no error
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadAxisErrorCode_nJ(self, boxID, rbtID, result):
        command = 'ReadAxisErrorCode,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 31
    *	@param brief: Read current FSM
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0] : Current FSM
    *	@param result[1] : FSM description
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCurFSM(self, boxID, rbtID, result):
        command = 'ReadCurFSM,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
      *	@index : 32
      *	@param brief: Read point pose, joint positions, UCS and TCP by point name
      *	@param boxID: Control box ID
      *	@param rbtID: Robot ID
      *	@param pointName
      *	@param result[0]-result[5] : joint positions
      *	@param result[6]-result[11] : pose
      *	@param result[12]-result[17] : TCP pose
      *	@param result[18]-result[23] : UCS pose
      *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadPointByName(self, boxID, rbtID, pointName, result):
        command = 'ReadPointByName,'
        command += str(rbtID) + ','
        command += pointName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
      *	@index : 33
      *	@param brief: Read point pose, joint positions, UCS and TCP by point name
      *	@param boxID: Control box ID
      *	@param rbtID: Robot ID
      *	@param pointName: Point name 
      *	@param result[0]-result[n-1]: joint positions
      *	@param result[n]-result[2n-1]: pose
      *	@param result[2n]-result[3n-1]: TCP pose
      *	@param result[3n]-result[4n-1]: UCS pose
      *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadPointByName_nJ(self, boxID, rbtID, pointName, result):
        command = 'ReadPointByName,'
        command += str(rbtID) + ','
        command += pointName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
      *	@index : 34
      *	@param brief: Read FSM from CPS
      *	@param boxID: Control box ID
      *	@param rbtID: Robot ID
      *	@param result[0]: Current FSM
      *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_ReadCurFSMFromCPS(self, boxID, rbtID, result):
        command = 'ReadCurFSM,'
        command += str(rbtID) + ','
        command += ';'
        nRet = self.g_clients[boxID].sendAndRecv(command, result)
        if len(result) < 1:
            return nRet
        strRes = self.dic_FSM.get(int(result[0]))
        result.append(strRes)
        return nRet

    '''
    *	@index : 35
    *	@param brief:  Read robot state
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: Moving state
    *   @param result[1]: Enable state
    *   @param result[2]: Error state
    *   @param result[3]: Error code
    *   @param result[4]: Error axis ID
    *   @param result[5]: Breaking status
    *   @param result[6]: Pause state
    *   @param result[7]: Moving blending done state
        '''
    def HRIF_ReadRobotFlags(self, boxID, rbtID, result):
        result2 = []
        command = 'ReadRobotState,'
        command += str(rbtID) + ','
        command += ';'
        DataRet = self.g_clients[boxID].sendAndRecv(command, result2)
        for i in range(8):
            result += str(result2[i])
        return DataRet

    '''
      *	@index : 36
      *	@param brief: Read point list as name
      *	@param boxID: Control box ID
      *	@param rbtID: Robot ID
      *	@param result: Point list
      *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_ReadPointList(self, boxID, rbtID, result):
        command = 'ReadPointList,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 6 Interfaces for position, velocity and current reading
    #

    '''
    *	@index : 1
    *	@param brief: Read actual pose and joint positions
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: joint positions
    *	@param result[6]-result[11]: pose
    *	@param result[12]-result[17]: TCP pose 
    *	@param result[18]-result[23]: UCS pose
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActPos(self, boxID, rbtID, result):
        command = 'ReadActPos,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 1
    *	@param brief: Read actual pose and joint positions
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]: joint positions
    *	@param result[n]-result[2n-1]: pose
    *	@param result[2n]-result[3n-1]: TCP pose
    *	@param result[3n]-result[4n-1]: UCS pose
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActPos_nJ(self, boxID, rbtID, result):
        command = 'ReadActPos,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Read command joint positions
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: Joint command positions
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCmdJointPos(self, boxID, rbtID, result):
        command = 'ReadCmdPos,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 4
    *	@param brief: Read command joint positions
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]: Joint command positions
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCmdJointPos_nJ(self, boxID, rbtID, result):
        command = 'ReadCmdPos,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Read actual joint positions
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: Joint actual positions
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActJointPos(self, boxID, rbtID, result):
        command = 'ReadActACS,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 6
    *	@param brief: Read actual joint positions
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]: Joint actual positions
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActJointPos_nJ(self, boxID, rbtID, result):
        command = 'ReadActACS,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Read command pose of TCP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: TCP command pose
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCmdTcpPos(self, boxID, rbtID, result):
        command = 'ReadCmdPos,'
        command += str(rbtID) + ','
        command += ';'
        errorCode = self.g_clients[boxID].sendAndRecv(command, result)
        if errorCode != 0:
            return errorCode
        del result[6]
        del result[6]
        del result[6]
        del result[6]
        del result[6]
        del result[6]
        return errorCode

    '''
    *	@index : 8
    *	@param brief: Read actual pose of TCP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: TCP actual pose
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActTcpPos(self, boxID, rbtID, result):
        retData = []
        errorCode = self.HRIF_ReadActPos(boxID, rbtID, retData)
        if errorCode != 0:
            return errorCode
        for i in range(6, 12):
            result.append(retData[i])
        return errorCode

    '''
    *	@index : 9
    *	@param brief: Read command velocity of joint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]:Joint command velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCmdJointVel(self, boxID, rbtID, result):
        command = 'ReadCmdJointVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 10
    *	@param brief: Read command velocity of joint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]:Joint command velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCmdJointVel_nJ(self, boxID, rbtID, result):
        command = 'ReadCmdJointVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 11
    *	@param brief: Read actual velocity of joint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: Joint actual velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActJointVel(self, boxID, rbtID, result):
        command = 'ReadActJointVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 12
    *	@param brief: Read actual velocity of joint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]: Joint actual velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActJointVel_nJ(self, boxID, rbtID, result):
        command = 'ReadActJointVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 13
    *	@param brief: Read command velocity of TCP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5] : TCP command velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCmdTcpVel(self, boxID, rbtID, result):
        command = 'ReadCmdTcpVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 14
    *	@param brief: Read actual velocity of TCP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: TCP actual velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActTcpVel(self, boxID, rbtID, result):
        command = 'ReadActTcpVel,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 15
    *	@param brief: Read command current of joint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: Joint command current
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCmdJointCur(self, boxID, rbtID, result):
        command = 'ReadCmdJointCur,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 16
    *	@param brief: Read command current of joint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]: Joint command current
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCmdJointCur_nJ(self, boxID, rbtID, result):
        command = 'ReadCmdJointCur,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 17
    *	@param brief: Read actual current of joint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: Joint actual current
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActJointCur(self, boxID, rbtID, result):
        command = 'ReadActJointCur,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 18
    *	@param brief: Read actual current of joint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[n-1]: Joint actual current
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActJointCur_nJ(self, boxID, rbtID, result):
        command = 'ReadActJointCur,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 19
    *	@param brief:  Read End velocity of TCP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0] : TCP command velocity
    *	@param result[1] : TCP actual velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadTcpVelocity(self, boxID, rbtID, result):
        command = 'ReadTcpVelocity,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 7 Interfaces for calculation
    #

    '''
    *	@index : 1
    *	@param brief: Quaternion to Euler angle
    *	@param boxID: Control box ID
    *	@param dQuaW : Quaternion W
    *	@param dQuaX : Quaternion X
    *	@param dQuaY : Quaternion Y
    *	@param dQuaZ : Quaternion Z
    *	@param result[0] : Euler angle RX
    *	@param result[1] : Euler angle RY
    *	@param result[2] : Euler angle RZ
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_Quaternion2RPY(self, boxID, dQuaW, dQuaX, dQuaY, dQuaZ, result):
        command = 'Quaternion2RPY,0,'
        command += str(dQuaW) + ','
        command += str(dQuaX) + ','
        command += str(dQuaY) + ','
        command += str(dQuaZ) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Euler angle to Quaternion
    *	@param boxID: Control box ID
    *	@param Rx : Euler angle RX
    *	@param Ry : Euler angle RY
    *	@param Rz :Euler angle RZ 
    *	@param result[0] : Quaternion W
    *	@param result[1] : Quaternion X
    *	@param result[2] : Quaternion Y
    *	@param result[3] : Quaternion Z
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_RPY2Quaternion(self, boxID, Rx, Ry, Rz, result):
        command = 'RPY2Quaternion,0,'
        command += str(Rx) + ','
        command += str(Ry) + ','
        command += str(Rz) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Inverse kinematics transformation from pose to joint positions
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param rawPCS : pose in specified UCS and TCP
    *	@param rawACS : Reference joint coordinates
    *	@param tcp : TCP pose
    *	@param ucs : UCS pose
    *	@return result[0]-result[5] : Inverse solution of J1~J6
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetInverseKin(self, boxID, rbtID, rawPCS, rawACS, tcp, ucs, result):
        command = 'PCS2ACS,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(rawPCS[i]) + ','
        for i in range(0, 6):
            command += str(rawACS[i]) + ','
        for i in range(0, 6):
            command += str(tcp[i]) + ','
        for i in range(0, 6):
            command += str(ucs[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    '''
    *	@index : 4
    *	@param brief: Inverse kinematics transformation from pose to joint positions
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param rawPCS : pose in specified UCS and TCP
    *	@param rawACS : Reference joint coordinates
    *	@param tcp : TCP pose 
    *	@param ucs : UCS pose
    *	@return result[0]-result[n-1] : Inverse solution of J1~J6
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetInverseKin_nJ(self, boxID, rbtID, rawPCS, rawACS, tcp, ucs, result):
        command = 'PCS2ACS,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(rawPCS[i]) + ','
        for i in range(0, len(rawACS)):
            command += str(rawACS[i]) + ','
        for i in range(0, 6):
            command += str(tcp[i]) + ','
        for i in range(0, 6):
            command += str(ucs[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Forward kinematics transformation from joint positions to pose
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param rawACS : joint positions
    *	@param tcp : TCP pose for the target
    *	@param ucs : UCS pose for the target 
    *	@return result[0]-result[5] : pose in specified UCS and TCP
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetForwardKin(self, boxID, rbtID, rawACS, tcp, ucs, result):
        command = 'ACS2PCS,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(rawACS[i]) + ','
        for i in range(0, 6):
            command += str(tcp[i]) + ','
        for i in range(0, 6):
            command += str(ucs[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 6
    *	@param brief: Forward kinematics transformation from joint positions to pose
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param rawACS : joint positions
    *	@param tcp : TCP pose for the target
    *	@param ucs : UCS pose for the target
    *	@return result[0]-result[5] : pose in specified UCS and TCP
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetForwardKin_nJ(self, boxID, rbtID, rawACS, tcp, ucs, result):
        command = 'ACS2PCS,'
        command += str(rbtID) + ','
        for i in range(0, len(rawACS)):
            command += str(rawACS[i]) + ','
        for i in range(0, 6):
            command += str(tcp[i]) + ','
        for i in range(0, 6):
            command += str(ucs[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Pose transformation from Base to UCS&TCP
    *	@param boxID: Control box ID
    *	@param Base : Pose in Base coordinate system
    *	@param TCP : TCP pose for the target
    *	@param UCS : UCS pose for the target
    *	@return result[0-5] : Pose in the specified UCS and TCP
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_Base2UcsTcp(self, boxID, Base, TCP, UCS, result):
        command = 'Base2UcsTcp,0,'
        for i in range(0, 6):
            command += str(Base[i]) + ','
        for i in range(0, 6):
            command += str(TCP[i]) + ','
        for i in range(0, 6):
            command += str(UCS[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 8
    *	@param brief: Pose transformation from UCS&TCP to Base
    *	@param boxID: Control box ID
    *	@param UcsTcp : Pose in speicified UCS and TCP
    *	@param TCP : TCP pose for dCoord 
    *	@param UCS : UCS pose for dCoord
    *	@return result[0]-result[5] : pose in Base coordinate system
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_UcsTcp2Base(self, boxID, UcsTcp, TCP, UCS, result):
        command = 'UcsTcp2Base,0,'
        for i in range(0, 6):
            command += str(UcsTcp[i]) + ','
        for i in range(0, 6):
            command += str(TCP[i]) + ','
        for i in range(0, 6):
            command += str(UCS[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 9
    *	@param brief: Pose addition calculation
    *	@param boxID: Control box ID
    *	@param pos1 : Pose of point 1
    *	@param pos2 : Pose of point 2
    *	@return result[0-5] : Calculation result
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PoseAdd(self, boxID, pos1, pos2, result):
        command = 'PoseAdd,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        for i in range(0, 6):
            command += str(pos2[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 10
    *	@param brief: Pose subtraction calculation
    *	@param boxID: Control box ID
    *	@param pos1 : Pose of point 1
    *	@param pos2 : Pose of point 2
    *	@return result[0]-result[5] : Calculation result
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PoseSub(self, boxID, pos1, pos2, result):
        command = 'PoseSub,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        for i in range(0, 6):
            command += str(pos2[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 11
    *	@param brief: Pose transformation through combined caculations, from P1 based on Base coordinate system to P3 based on UCS with P2
    *	@param boxID: Control box ID
    *	@param pos1 : Pose of point 1
    *	@param pos2 : Pose of point 2
    *	@return result[0-5] : Calculation result, P3
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PoseTrans(self, boxID, pos1, pos2, result):
        command = 'PoseTrans,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        for i in range(0, 6):
            command += str(pos2[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Inverse kinematics transformation for pose
    *	@param boxID: Control box ID
    *	@param pos1 : Pose of point 1
    *	@return result[0]-result[5] : Pose of calculation result
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PoseInverse(self, boxID, pos1, result):
        command = 'PoseInverse,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 13
    *	@param brief: Calculate points distance
    *	@param boxID: Control box ID
    *	@param pos1 : Pose of point 1
    *	@param pos1 : Pose of point 2
    *	@return result[0] : Points distance (mm)
    *	@return result[1] : Angle between poses
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PoseDist(self, boxID, pos1, pos2, result):
        command = 'CalPointDistance,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        for i in range(0, 6):
            command += str(pos2[i]) + ','
        command += ';'
        ret = self.g_clients[boxID].sendAndRecv(command, result)
        if ret == 20005:
            command = 'PoseDist,0,'
            for i in range(0, 6):
                command += str(pos1[i]) + ','
            for i in range(0, 6):
                command += str(pos2[i]) + ','
            command += ';'
            ret = self.g_clients[boxID].sendAndRecv(command, result)
        for i in range(len(result)):
            if isinstance(result[i], str):
                try:
                    result[i] = float(result[i])
                except ValueError:
                    pass

        return ret

    '''
    *	@index : 14
    *	@param brief: Linear interpolation calculation for pose
    *	@param boxID: Control box ID
    *	@param pos1 : Pose of point 1
    *	@param pos2 : Pose of point 2
    *	@param alpha: Interpolation scale
    *	@return result[0]-result[5] : Calculation result, pose of point 3
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PoseInterpolate(self, boxID, pos1, pos2, alpha, result):
        command = 'PoseInterpolate,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        for i in range(0, 6):
            command += str(pos2[i]) + ','
        command += str(alpha) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 15
    *	@param brief: Calculate the rotation center. P1,P2,P3 are the points before rotation and P4,P5,P6 are the points after rotation
    *	@param boxID: Control box ID
    *	@param pose1 : Pose of point 1
    *	@param pose2 : Pose of point 2
    *	@param pose3 : Pose of point 3
    *	@param pose4 : Pose of point 4
    *	@param pose5 : Pose of point 5
    *	@param pose6 : Pose of point 6
    *	@return result[0]-result[5] : Calculation result, UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PoseDefdFrame(self, boxID, pos1, pos2, pos3, pos4, pos5, pos6, result):
        command = 'PoseDefdFrame,0,'
        for i in range(0, 3):
            command += str(pos1[i]) + ','
        for i in range(0, 3):
            command += str(pos2[i]) + ','
        for i in range(0, 3):
            command += str(pos3[i]) + ','
        for i in range(0, 3):
            command += str(pos4[i]) + ','
        for i in range(0, 3):
            command += str(pos5[i]) + ','
        for i in range(0, 3):
            command += str(pos6[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 16
    *	@param brief:  Calculate UCS through 3-point plane
    *	@param boxID: Control box ID
    *	@param pos1 : Position of point 1 in Base and specified TCP
    *	@param pos2 : Position of point 2 in Base and specified TCP
    *	@param pos3 : Position of point 3 in Base and specified TCP
    *	@return result[0]-result[5] :  Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_CalUcsPlane(self, boxID, pos1, pos2, pos3, result):
        command = 'CalUcsPlane,0,'
        for i in range(0, 3):
            command += str(pos1[i]) + ','
        for i in range(0, 3):
            command += str(pos2[i]) + ','
        for i in range(0, 3):
            command += str(pos3[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 17
    *	@param brief: Calculate UCS through 2-point linee
    *	@param boxID: Control box ID
    *	@param pos1: Pose of point 1 in Base and specified TCP
    *	@param pos2: Pose of point 2 in Base and specified TCP
    *	@return result[0]-result[5]: Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_CalUcsLine(self, boxID, pos1, pos2, result):
        command = 'CalUcsLine,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        for i in range(0, 6):
            command += str(pos2[i]) + ','

        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 18
    *	@param brief: Calculate TCP through 3-point
    *	@param boxID: Control box ID
    *	@param pos1 : Pose of point 1 in Base and system default TCP
    *	@param pos2 : Pose of point 2 in Base and system default TCP
    *	@param pos3 : Pose of point 3 in Base and system default TCP
    *	@return result[0]-result[2]: Position of TCP
    *	@return result[3]-result[5]: Orientation of TCP, usually 0
    *	@return result[6]: quality of the result, 0 for good, 1 for poor, 2 for abnormal
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_CalTcp3P(self, boxID, pos1, pos2, pos3, result):
        command = 'CalTcp3P,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        for i in range(0, 6):
            command += str(pos2[i]) + ','
        for i in range(0, 6):
            command += str(pos3[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 19
    *	@param brief: Calculate TCP through 4-point
    *	@param boxID: Control box ID
    *	@param pos1 : Pose of point 1 in Base and system default TCP
    *	@param pos2 : Pose of point 2 in Base and system default TCP
    *	@param pos3 : Pose of point 3 in Base and system default TCP
    *	@param pos4 : Pose of point 4 in Base and system default TCP
    *	@return result[0]-result[2]: Position of TCP
    *	@return result[3]-result[5]: Orientation of TCP, usually 0
    *	@return result[6] : quality of the result, 0 for good, 1 for poor, 2 for abnormal
    *	@return result[7-10] : error index for the 4 source points, 0 for abnormal, 1 for normal
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_CalTcp4P(self, boxID, pos1, pos2, pos3, pos4, result):
        command = 'CalTcp4P,0,'
        for i in range(0, 6):
            command += str(pos1[i]) + ','
        for i in range(0, 6):
            command += str(pos2[i]) + ','
        for i in range(0, 6):
            command += str(pos3[i]) + ','
        for i in range(0, 6):
            command += str(pos4[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    
    '''
    *	@index : 20
    *	@param brief: Calculate TCP orientation
    *	@param boxID: Control box ID
    *	@param rbtID : Robot ID
    *	@param dUcs : Coordinates and rotation angles in user coordinate system
    *	@param dPcs : Coordinates and rotation angles of TCP
    *	@param result[0]-result[2]: Calculated rotation angles 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_CalTCPOrt(self, boxID, rbtID, dUcs, dPcs, result ):
        command = 'CalTCPOrt,'
        command += str(rbtID) +','
        for i in range(6):
            command += str(dUcs[i]) + ','
        for i in range(6):
            command += str(dPcs[i]) + ','
        command += ';'
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 21
    *	@param brief: Calculate inverse dynamics results
    *	@param boxID: Control box ID
    *	@param dPose_J1~6 : Joint position
    *	@param dVel_J1~6 : Joint velocities
    *	@param dAcc_J1~6 : Joint accelerations
    *	@param result[0]-result[5]: Joint torques calculated by inverse dynamics (Nm)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetInverseDynamics(self, boxID, pose, vel, acc, result):
        command = 'GetInverseDynamics,0,'
        for i in range(0, 6):
            command += str(pose[i]) + ','
        for i in range(0, 6):
            command += str(vel[i]) + ','
        for i in range(0, 6):
            command += str(acc[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)


    #
    # part 8 Interfaces for TCP and UCS
    #

    '''
    *	@index : 1
    *	@param brief: Set current UCS
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param TCP: Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_SetTCP(self, boxID, rbtID, TCP):
        result = []
        command = 'SetCurTCP,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(TCP[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief:Set current UCS
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param UCS: Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetUCS(self, boxID, rbtID, UCS):
        result = []
        command = 'SetCurUCS,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(UCS[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Read current TCP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@return result[0]-result[5] : Pose of TCP
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCurTCP(self, boxID, rbtID, result):
        command = 'ReadCurTCP,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Read current UCS
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@return result[0]-result[5] : Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadCurUCS(self, boxID, rbtID, result):
        command = 'ReadCurUCS,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Set current TCP By Name
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param TcpName: TCP name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetTCPByName(self, boxID, rbtID, TcpName):
        result = []
        command = 'SetTCPByName,'
        command += str(rbtID) + ','
        command += str(TcpName) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief:Set current UCS By Name
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param UcsName: UCS name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetUCSByName(self, boxID, rbtID, UcsName):
        result = []
        command = 'SetUCSByName,'
        command += str(rbtID) + ','
        command += str(UcsName) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Read TCP By Name
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param TCP: TCP name 
    *	@return result[0]-result[5] : Pose of TCP
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadTCPByName(self, boxID, rbtID, TCP, result):
        command = 'ReadTCPByName,'
        command += str(rbtID) + ','
        command += str(TCP) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 8
    *	@param brief: Read UCS By Name
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param UCS: UCS name
    *	@return result[0-5] : Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadUCSByName(self, boxID, rbtID, UCS, result):
        command = 'ReadUCSByName,'
        command += str(rbtID) + ','
        command += str(UCS) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 9
    *	@param brief: Confige TCP 
    *	@param boxID: Control box ID
    *	@param sTcpName: TCP name
    *	@param dTcp_X-dTcp_Rz : Pose of TCP
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ConfigTCP(self, boxID, name, pos):
        result = []
        command = 'ConfigTCP,0,'
        command += name + ','
        for i in range(0, 6):
            command += str(pos[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 10
    *	@param brief: Confige UCS
    *	@param boxID: Control box ID
    *	@param sUcsName: UCS name
    *	@param dTcp_X-dTcp_Rz : Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ConfigUCS(self, boxID, name, pos):
        result = []
        command = 'ConfigUCS,0,'
        command += name + ','
        for i in range(0, 6):
            command += str(pos[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 11
    *	@param brief: Read TCP list
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result: vector of TCP list
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadTCPList(self, boxID, rbtID, result):
        command = 'ReadTCPList,'
        command += str(rbtID) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Read UCS list
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result: vector of UCS list
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadUCSList(self, boxID, rbtID, result):
        command = 'ReadUCSList,'
        command += str(rbtID) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 13
    *	@param brief: Set the current base mounting angle
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param rotation: Set base rotation angle
    *	@param tilt: Set base tilt angle
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetBaseInstallingAngle(self, boxID, rbtID, rotation, tilt):
        result = []
        command = 'SetBaseInstallingAngle,'
        command += str(rbtID) + ','
        command += str(rotation) + ','
        command += str(tilt) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 14
    *	@param brief: Get the current base mounting angle
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: Get base rotation angle
    *	@param result[1]: Get base tilt angle 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetBaseInstallingAngle(self, boxID, rbtID, result):
        command = 'GetBaseInstallingAngle,'
        command += str(rbtID) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 15
    *	@param brief: Set default TCP (Tool Center Point)
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param TCP: Name of the TCP to be set as default
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetDftTCP(self, boxID, rbtID, TCP):
        command = 'SetDftTCP,'
        command += str(rbtID) +','
        command += str(TCP) + ','
        command += ';'
        print(command)
        result = []
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 16
    *	@param brief: Read current coordinates of the robot arm
    *   @details: Get joint coordinates and user coordinates of the robot arm in current state by inputting TCP and UCS names
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param TCP : Name of the tool center point
    *	@param UCS : Name of the user coordinate system
    *	@param result[0]-result[5]: Current joint coordinates
    *	@param result[6]-result[11]: Current user coordinates
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActCoord(self, boxID, rbtID, TCP, UCS, result):
        command = 'ReadActCoord,'
        command += str(rbtID) + ','
        command += TCP + ','
        command += UCS + ','
        command += ";"
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 17
    *	@param brief: Read current coordinates of the robot arm
    *   @details: Get joint coordinates and user coordinates of the robot arm in current state by inputting TCP and UCS names
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param TCP : Name of the tool center point
    *	@param UCS : Name of the user coordinate system
    *	@param result[0]-result[n-1]: Current joint coordinates
    *	@param result[n]-result[2n-1]: Current user coordinates
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadActCoord_nJ(self,boxID, rbtID,TCP,UCS, result):
        command = 'ReadActCoord,'
        command += str(rbtID) + ','
        command += TCP + ','
        command += UCS + ','
        command += ";"
        print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)


    #
    # part 9 Interfaces for force control
    #

    '''
    *	@index : 1
    *	@param brief: Set force control status
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param state : 0 for closed, 1 for open
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetForceControlState(self, boxID, rbtID, state):
        result = []
        command = 'SetForceControlState,'
        command += str(rbtID) + ','
        command += str(state) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Read force control status
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]:  0 for closed, 1 for seeking, 2 for seeking completed, 3 for free drive
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadForceControlState(self, boxID, rbtID, result):
        command = 'ReadFTControlState,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Set force sensor direction align with TCP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param mode : 0 for not align with TCP, 1 for align with TCP 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetForceToolCoordinateMotion(self, boxID, rbtID, mode):
        result = []
        command = 'SetForceToolCoordinateMotion,'
        command += str(rbtID) + ','
        command += str(mode)
        command += ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Disable force control
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ForceControlInterrupt(self, boxID, rbtID):
        result = []
        command = 'GrpFCInterrupt,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Enable force control
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ForceControlContinue(self, boxID, rbtID):
        result = []
        command = 'GrpFCContinue,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Reset force sensor to zero
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetForceZero(self, boxID, rbtID):
        result = []
        command = 'SetForceZero,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Set max velocity of force seeking
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param MaxLinearVelocity : Max linear velocity
    *	@param MaxAngularVelocity : Max angular velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMaxSearchVelocities(self, boxID, rbtID, MaxLinearVelocity, MaxAngularVelocity):
        result = []
        command = 'HRSetMaxSearchVelocities,'
        command += str(rbtID) + ','
        command += str(MaxLinearVelocity) + ','
        command += str(MaxAngularVelocity) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 8
    *	@param brief: Set control freedom
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param freedom[0]-freedom[5]: 0 for closed / 1 for open
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetControlFreedom(self, boxID, rbtID, freedom):
        result = []
        command = 'HRSetControlFreedom,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(freedom[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 9
    *	@param brief: Set force control strategy
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param strategy: 0 for Compliant force and 1 for Constant force
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetForceControlStrategy(self, boxID, rbtID, strategy):
        result = []
        command = 'HRSetForceControlStrategy,'
        command += str(rbtID) + ','
        command += str(strategy)
        command += ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 10
    *	@param brief: Set force sensor pose
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param position[0]-position[5]: Pose
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetFreeDrivePositionAndOrientation(self, boxID, rbtID, position):
        result = []
        command = 'SetFTPosition,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(position[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 11
    *	@param brief: Set PID for force seeking
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param fP: PID 
    *	@param fI: PID
    *	@param fD: PID 
    *	@param tP: PID
    *	@param tI: PID
    *	@param tD: PID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetPIDControlParams(self, boxID, rbtID, fP, fI, fD, tP, tI, tD):
        result = []
        command = 'HRSetPIDControlParams,'
        command += str(rbtID) + ','
        command += str(fP)
        command += ','
        command += str(fI)
        command += ','
        command += str(fD)
        command += ','
        command += str(tP)
        command += ','
        command += str(tI)
        command += ','
        command += str(tD)
        command += ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Set mass parameters
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param mass:  Mass parameters
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMassParams(self, boxID, rbtID, mass):
        result = []
        command = 'HRSetMassParams,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(mass[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 13
    *	@param brief: Set damp parameters
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param damp:  Damp parameters
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetDampParams(self, boxID, rbtID, damp):
        result = []
        command = 'HRSetDampParams,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(damp[i]) + ','
        command += ';'
        retData = self.g_clients[boxID].sendAndRecv(command, result)
        return retData

    '''
    *	@index : 14
    *	@param brief: Set stiffness parameters
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param stiff: Stiffness parameters
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetStiffParams(self, boxID, rbtID, stiff):
        result = []
        command = 'HRSetStiffParams,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(stiff[i]) + ','
        command += ';'
        retData = self.g_clients[boxID].sendAndRecv(command, result)
        return retData

    '''
    *	@index : 15
    *	@param brief: Set force control goal
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param force_goal: Goal values
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetForceControlGoal(self, boxID, rbtID, force_goal):
        result = []
        command = 'HRSetControlGoal,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(force_goal[i]) + ','
        for i in range(0, 6):
            command += str(0) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 16
    *	@param brief:  Set control seeking goal
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param forcegoal: Seeking force
    *	@param distance: Seeking distance
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetControlGoal(self, boxID, rbtID, forcegoal, distance):
        result = []
        command = 'HRSetControlGoal,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(forcegoal[i]) + ','
        for i in range(0, 6):
            command += str(distance[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 17
    *	@param brief: Set force data limit
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param max: Max limit
    *	@param min: Min limit
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetForceDataLimit(self, boxID, rbtID, max, min):
        result = []
        command = 'HRSetForceDataLimit,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(max[i]) + ','
        for i in range(0, 6):
            command += str(min[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 18
    *	@param brief: Set force distance limit
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param allowDistance: Allowed seeking distance
    *	@param strengthLevel: Power term for the deviation from boundary. 2 for square, 3 for cubic
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetForceDistanceLimit(self, boxID, rbtID, allowDistance, strengthLevel):
        result = []
        command = 'HRSetForceDistanceLimit,'
        command += str(rbtID) + ','
        command += str(allowDistance) + ','
        command += str(strengthLevel) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 19
    *	@param brief: Set force free drive mode
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param state: 0 for closed, 1 for open
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetForceFreeDriveMode(self, boxID, rbtID, state):
        result = []
        command = 'SetFTFreeDriveState,'
        command += str(rbtID) + ','
        command += str(state) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 20
    *	@param brief: Set speed mode for force free drive
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nMode: Speed mode, 0 as normal mode, 1 as slow mode, 2 as fast mode, 3 as Welding mode
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetFTFreeDriveSpeedMode(self, boxID, rbtID, mode):
        result = []
        command = 'SetFTFreeDriveSpeedMode,'
        command += str(rbtID) + ','
        command += str(mode) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 21
    *	@param brief: Read force control calibration data
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: speed mode, 0 as normal mode, 1 as slowmode, 2 as fast mode, 3 as Welding mode
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadFTFreeDriveSpeedMode(self, boxID, rbtID, result):
        command = 'ReadFTFreeDriveSpeedMode,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 22
    *	@param brief: Read force control calibration data
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]:  Calibration data
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadFTCabData(self, boxID, rbtID, result):
        command = 'ReadFTCabData,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 23
    *	@param brief: ead  force data from the force sensor
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: Force data in the X direction
    *	@param result[1]: Force data in the Y direction 
    *	@param result[2]: Force data in the Z direction 
    *	@param result[3]: Force data in the RX direction
    *	@param result[4]: Force data in the RY direction
    *	@param result[5]: Force data in the RZ direction
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadFTData(self, boxID, rbtID, result):
        command = 'ReadForceData,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 24
    *	@param brief: Set the end freedom in free drive
    *	@param boxID: Control box ID
    *	@param df[0]-df[5]: The available freedom parameters in free drive
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetFreeDriveMotionFreedom(self, boxID, df):
        result = []
        command = 'SetFTMotionFreedom,0,'
        for i in range(0, 6):
            command += str(df[i]) + ','
        command += ';'
        # print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 25
    *	@param brief: Set force free drive translation compliance and rotation compliance
    *	@param boxID: Control box ID
    *	@param dLinear: translation compliance
    *	@param dAngular: rotation compliance
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetFTFreeFactor(self, boxID, dLinear, dAngular):
        result = []
        command = 'SetFTFreeFactor,0,'
        command += str(dLinear) + ','
        command += str(dAngular) + ',;'

        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 26
    *	@param brief: Set the maximum value, minimum value of the tangential force in the x/y direction and the maximum speed of lifting
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param Max: Max tangential force (N)
    *	@param Min: Min tangential force (N)
    *	@param Vel: Max lifting Velocity (mm/s)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetTangentForceBounds(self, boxID, rbtID, Max, Min, Vel):
        result = []
        command = 'SetTangentForceBounds,'
        command += str(rbtID) + ','
        command += str(Max) + ','
        command += str(Min) + ','
        command += str(Vel) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 27
    *	@param brief: Set the orientation compensation force size and vector direction [x,y,z] in FreeDrive mode
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dForce: Compensation force size(N)
    *	@param x-z: The vactor direction of compensation force based Base
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetFreeDriveCompensateForce(self, boxID, rbtID, force, x, y, z):
        result = []
        command = 'SetFreeDriveCompensateForce,'
        command += str(rbtID) + ','
        command += str(force) + ','
        command += str(x) + ','
        command += str(y) + ','
        command += str(z) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 28
    *	@param brief: Set the six-dimensional force activation threshold (force and torque)
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param ForceThreshold: Force activation threshold(N)
    *	@param TorqueThreshold: Torque activation threshold (Nm)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetFTWrenchThresholds(self, boxID, rbtID, force, torque):
        result = []
        command = 'SetFTWrenchThresholds,'
        command += str(rbtID) + ','
        command += str(force) + ','
        command += str(torque) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 29
    *	@param brief: Set the maximum linear speed and attitude angular speed of force free drive
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param vel: Max linear speed (mm/s)
    *	@param angular_vel: Max attitude angular speed (°/s)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMaxFreeDriveVel(self, boxID, rbtID, vel, angular_vel):
        result = []
        command = 'SetMaxFreeDriveVel,'
        command += str(rbtID) + ','
        command += str(vel) + ','
        command += str(angular_vel) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 30
    *	@param brief: Read the end degrees of freedom of the force free drive
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0-5]: The available freedom parameters in free drive
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadFTMotionFreedom(self, boxID, rbtID, result):
        command = 'ReadFTMotionFreedom,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 31
    *	@param brief: Set each degree of freedom (X/Y/Z/RX/RY/RZ) to force control the maximum distance of exploration
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param AllowDistance1-AllowDistance6: Max distance of exploration in all directions(mm)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMaxSearchDistance(self, boxID, rbtID, AllowDistance1, AllowDistance2, AllowDistance3, AllowDistance4,
                                  AllowDistance5, AllowDistance6):
        result = []
        command = 'HRSetMaxSearchDistance,'
        command += str(rbtID) + ','
        command += str(AllowDistance1) + ','
        command += str(AllowDistance2) + ','
        command += str(AllowDistance3) + ','
        command += str(AllowDistance4) + ','
        command += str(AllowDistance5) + ','
        command += str(AllowDistance6) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 32
    *	@param brief: Set the mean filter for force and torque
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param ForceState: Force data mean filtering switch, 0 as close, 1 as open
    *	@param TorqueState: Torque data mean filtering switch, 0 as close, 1 as open
    *	@param ForceLength: Mean filtering length for force data
    *	@param TorqueLength: Mean filtering length for torque data
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_SetFTMovingAvgFilterParams(self, boxID, rbtID, ForceState, TorqueState, ForceLength, TorqueLength):
        result = []
        command = 'HRSetFTMovingAvgFilterParams,'
        command += str(rbtID) + ','
        command += str(ForceState) + ','
        command += str(TorqueState) + ','
        command += str(ForceLength) + ','
        command += str(TorqueLength) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 33
    *	@param brief: Turn on/off force sensor _ Script with configuration
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param state: Set state for force senser
    *	@param FTMode: 0 for Compliant force and 1 for Constant force
    *	@param UCS: Tool
    *	@param vel[0]: Linear speed
    *	@param vel[1]: Angular speed
    *	@param forces : Target exploration force for all directions
    *	@param freedom : Freedom parameters for free drive exploration
    *	@param PID : fP,fI,fD,tP,tI,tD 
    *	@param Mass : Mass
    *	@param Damp : Damp
    *	@param Stiff : Stiffness
    *	@param return: open  force control, 0 as success, 1 as fail
    '''

    def HRIF_SetScriptForceControlState(self, boxID, rbtID, state, FTMode, UCS, TCP, vel, forces, freedom, PID, Mass,
                                        Damp, Stiff):
        result = []
        command = 'SetScriptForceControlState,'
        command += str(rbtID) + ','
        command += str(state) + ','
        command += str(FTMode) + ','
        command += str(UCS) + ','
        command += str(TCP) + ','
        for i in range(0, 2):
            command += str(vel[i]) + ','
        for i in range(0, 6):
            command += str(forces[i]) + ','
        for i in range(0, 6):
            command += str(freedom[i]) + ','
        for i in range(0, 6):
            command += str(PID[i]) + ','
        for i in range(0, 6):
            command += str(Mass[i]) + ','
        for i in range(0, 6):
            command += str(Damp[i]) + ','
        for i in range(0, 6):
            command += str(Stiff[i]) + ','
        command += ';'
        retData = self.g_clients[boxID].sendAndRecv(command, result)
        if retData == 0:
            while True:
                command = 'ReadFTControlState,'
                command += str(rbtID) + ','
                command += ';'
                retData = self.g_clients[boxID].sendAndRecv(command, result)
                if state == 1:
                    if int(result[0]) == 2:
                        break
                elif state == 0:
                    if int(result[0]) != 2:
                        time.sleep(0.2)
                        break
                time.sleep(0.2)
        return retData

    '''
    *	@index : 34
    *	@param brief: Set constant force control stability phase boundary
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param x-rz: Max distance of positive (mm)
    *	@param nx-nrz: Max distance of negative (mm)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetSteadyContactDeviationRange(self, boxID, rbtID, x, y, z, rx, ry, rz, nx, ny, nz, nrx, nry, nrz):
        result = []
        command = 'HRSetSteadyContactDeviationRange,'
        command += str(rbtID) + ','
        command += str(x) + ','
        command += str(y) + ','
        command += str(z) + ','
        command += str(rx) + ','
        command += str(ry) + ','
        command += str(rz) + ','
        command += str(nx) + ','
        command += str(ny) + ','
        command += str(nz) + ','
        command += str(nrx) + ','
        command += str(nry) + ','
        command += str(nrz) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 35
    *	@param brief: Set the distance threshold when the virtual wall begins to generate damping
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param depth: Threshold size
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetDepthThresholdForDampingArea(self, boxID, rbtID, depth):
        result = []
        command = 'SetDepthThresholdForDampingArea,'
        command += str(rbtID) + ','
        command += str(depth) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 36
    *	@param brief: Add a new safe plane
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param name: plane name
    *   @param UcsName: UCS Name
    *   @param mode: Mode
    *   @param display: display
    *   @param switch: switch
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_AddSafePlane(self, boxID, rbtID, name, UcsName, mode, display, switch):
        result = []
        command = 'AddSafePlane,'
        command += str(rbtID) + ','
        command += str(name) + ','
        command += str(UcsName) + ','
        command += str(mode) + ','
        command += str(display) + ','
        command += str(switch) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 37
    *	@param brief: Update SafePlane Info
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param name: plane name
    *   @param UcsName: UCS Name
    *   @param mode: Mode
    *   @param display: display
    *   @param switch: switch
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_UpdateSafePlane(self, boxID, rbtID, name, UcsName, mode, display, switch):
        result = []
        command = 'UpdateSafePlane,'
        command += str(rbtID) + ','
        command += name + ','
        command += UcsName + ','
        command += str(mode) + ','
        command += str(display) + ','
        command += str(switch) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 38
    *	@param brief: Delete Safe Plane
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param name: plane name
    *   @param UcsName: UCS Name
    *   @param mode: Mode
    *   @param display: display
    *   @param switch: switch
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_DelSafePlane(self, boxID, rbtID, name):
        result = []
        command = 'DelSafePlane,'
        command += str(rbtID) + ','
        command += name + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 39
    *	@param brief: Get SafePlane List
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param result: SafePlane List
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadSafePlaneList(self, boxID, rbtID, result):
        command = 'ReadSafePlane,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 40
    *	@param brief: Read SafePlane Info
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param name: plane name
    *   @param result[0]: UCS Name
    *   @param result[1]: Mode
    *   @param result[2]: display
    *   @param result[3]: switch
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadSafePlane(self, boxID, rbtID, name, result):
        command = 'ReadSafePlane,'
        command += str(rbtID) + ','
        command += name + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 41
    *	@param brief: Set calibration parameters
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param calibrationForce: Set calibration force in XYZ
    *   @param torque: Set calibration moment in XYZ
    *   @param gravity: Get gravity
    *   @param cmOffset: Set center of gravity offset in XYZ
    *   @param installRotationAngel: Set current base mounting Installation angle
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetInitializeForceSensor(self, boxID, rbtID, calibrationForce, torque, gravity, cmOffset, installRotationAngel):
        result = []
        command = 'SetInitializeForceSensor,'
        command += str(rbtID) + ','
        for i in range(len(calibrationForce)):
            command += str(calibrationForce[i]) + ','
        for i in range(len(torque)):
            command += str(torque[i]) + ','
        command += str(gravity) + ','
        for i in range(len(cmOffset)):
            command += str(cmOffset[i]) + ','
        command += str(installRotationAngel) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 42
    *	@param brief: Get calibration parameters
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param result[0]-result[2]: Get calibration force in XYZ
    *   @param result[3]-result[5]: Get calibration moment in XYZ
    *   @param result[6]: Get gravity
    *   @param result[7]-result[9]: Get center of gravity offset in XYZ
    *   @param result[10]: Get current base mounting Installation angle
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetLastCalibParams(self, boxID, rbtID, result):
        command = 'GetLastCalibParams,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 43
    *	@param brief: Set the calibration data for the force sensor
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param num: Number of calibration points
    *   @param Point: Point data for force control calibration
    *	
    *	@return : nRet=0 : Function call succeeded
    *    
    '''
    def HRIF_SetFTCalibration(self, boxID, rbtID, num, Point):
        result = []
        command = 'SetFTCalibration,'
        command += str(rbtID) + ','
        for row in Point: 
            for value in row:
                command += str(value) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 44
    *	@param brief: Read  force data from the force sensor
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: Force data in the X direction
    *	@param result[1]: Force data in the Y direction
    *	@param result[2]: Force data in the Z direction
    *	@param result[3]: Force data in the RX direction
    *	@param result[4]: Force data in the RY direction
    *	@param result[5]: Force data in the RZ direction
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadForceData(self, boxID, rbtID, result):
        command = 'ReadForceData,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 45
    *	@param brief: Set current UCS
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param ucs:  Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *    
    '''
    def HRIF_SetFTUCS(self, boxID, rbtID, ucs):
        result = []
        command = 'SetFTUCS,'
        command += str(rbtID) + ','
        for item in ucs:
            command += str(item) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 46
    *	@param brief: Read current UCS
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]-result[5]: Pose of UCS
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadFTUCS(self, boxID, rbtID, result):
        command = 'ReadFTUCS,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)



    #
    # part 10 Interfaces for moving
    #

    '''
    *	@index : 1
    *	@param brief: Start joint short jog
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param axisId: Axis ID, 0~5
    *	@param direction: Moving direction, 0 for negative and 1 for positive
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ShortJogJ(self, boxID, rbtID, axisId, direction):
        result = []
        command = 'ShortJogJ,'
        command += str(rbtID) + ','
        command += str(axisId) + ','
        command += str(direction) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Cartesian short jog
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param pcsId: Axis ID, 0~5
    *	@param direction:  Moving direction, 0 for negative and 1 for positive
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ShortJogL(self, boxID, rbtID, pcsId, direction):
        result = []
        command = 'ShortJogL,'
        command += str(rbtID) + ','
        command += str(pcsId) + ','
        command += str(direction) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Start joint long jog
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param axisId: Axis ID, 0~5
    *	@param direction: Moving direction, 0 for negative and 1 for positive
    *	@param state: 0 for closed and 1 for open
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_LongJogJ(self, boxID, rbtID, axisId, direction, state):
        result = []
        command = 'LongJogJ,'
        command += str(rbtID) + ','
        command += str(axisId) + ','
        command += str(direction) + ','
        command += str(state) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Start cartesian long jog
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param pcsId:  Axis ID, 0~5 
    *	@param direction: Moving direction, 0 for negative and 1 for positive
    *	@param state: 0 for closed and 1 for open 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_LongJogL(self, boxID, rbtID, pcsId, direction, state):
        result = []
        command = 'LongJogL,'
        command += str(rbtID) + ','
        command += str(pcsId) + ','
        command += str(direction) + ','
        command += str(state) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)


    '''
    *	@index : 5
    *	@param brief: Continue long jog. Successively call this function after HRIF_ShortJogL or HRIF_LongJogJ with less than 500 ms interval to keep continuous moving
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_LongMoveEvent(self, boxID, rbtID):
        result = []
        command = 'LongMoveEvent,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    ''' 
    *	@index : 6
    *	@param brief: Check if the motion is done
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: 1 as done, 0 for as done 
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_IsMotionDone(self, boxID, rbtID, result):
        result.clear()
        ret = []
        errorCode = self.HRIF_ReadRobotState(boxID, rbtID, ret)
        if errorCode != 0:
            return errorCode
        result.append(ret[11] == "1" and ret[0] == "0")
        return errorCode

    ''' 
    *	@index : 7
    *	@param brief: Check if the waypoint blending is done
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: 1 as done, 0 as not done
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_IsBlendingDone(self, boxID, rbtID, result):
        ret = []
        command = 'ReadRobotState,'
        command += str(rbtID) + ','
        command += ';'
        net = self.g_clients[boxID].sendAndRecv(command, ret)
        if net != 0:
            return net
        if (ret[1] == 0 and ret[2] == 1 and ret[7] == 1 and ret[8] == 1 and ret[9] == 0 and ret[10] == 0):
            return 20018
        if (int(ret[11]) == 1):
            result.append(True)
        else:
            result.append(False)
        return net

    '''
    *	@index : 8
    *	@param brief: Start waypoint move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param type : Move type, 0 for MoveJ, 1 for MoveL
    *	@param points : Target pose, invalid when IsUseJoint equals 1. Target joint positions is obtained through inversely solving from this pose when IsUseJoint equals 0
    *	@param RawACSpoints : Target joint positions when IsUseJoint equals 1; Reference joint positions for the inversely solving when IsUseJoint equals 0.
    *	@param tcp : Target TCP name, invalid when IsUseJoint equals 1, "TCP" is valid as default
    *	@param ucs : Target UCS name, invalid when IsUseJoint equals 1, "Base" is valid as default
    *	@param speed : Motion speed, mm/s or °/s
    *	@param acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_WayPointEx(self, boxID, rbtID, type, points, RawACSpoints, tcp, ucs, speed, acc, radius, isJoint, isSeek,
                        bit, state, cmdID):
        result = []
        command = 'WayPointEx,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(points[i]) + ','
        for i in range(0, 6):
            command += str(RawACSpoints[i]) + ','
        for i in range(0, 6):
            command += str(ucs[i]) + ','
        for i in range(0, 6):
            command += str(tcp[i]) + ','
        command += str(speed) + ','
        command += str(acc) + ','
        command += str(radius) + ','
        command += str(type) + ','
        command += str(isJoint) + ','
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += cmdID + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 9
    *	@param brief: Start waypoint move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param type : Move type, 0 for MoveJ, 1 for MoveL
    *	@param points : Target pose, invalid when IsUseJoint equals 1. Target joint positions is obtained through inversely solving from this pose when IsUseJoint equals 0
    *	@param RawACSpoints : Target joint positions when IsUseJoint equals 1; Reference joint positions for the inversely solving when IsUseJoint equals 0.
    *	@param tcp : Target TCP name, invalid when IsUseJoint equals 1, "TCP" is valid as default
    *	@param ucs : Target UCS name, invalid when IsUseJoint equals 1, "Base" is valid as default
    *	@param speed : Motion speed, mm/s or °/s
    *	@param acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_WayPointEx_nJ(self, boxID, rbtID, type, points, RawACSpoints, tcp, ucs, speed, acc, radius, isJoint, isSeek,
                        bit, state, cmdID):
        result = []
        command = 'WayPointEx,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(points[i]) + ','
        for i in range(0, len(RawACSpoints)):
            command += str(RawACSpoints[i]) + ','
        for i in range(0, 6):
            command += str(ucs[i]) + ','
        for i in range(0, 6):
            command += str(tcp[i]) + ','
        command += str(speed) + ','
        command += str(acc) + ','
        command += str(radius) + ','
        command += str(type) + ','
        command += str(isJoint) + ','
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += cmdID + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 10
    *	@param brief: Start waypoint move.
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param type : Move type, 0 for MoveJ, 1 for MoveL
    *	@param points : Target pose, invalid when IsUseJoint equals 1. Target joint positions is obtained through inversely solving from this pose when IsUseJoint equals 0
    *	@param RawACSpoints : Target joint positions when IsUseJoint equals 1; Reference joint positions for the inversely solving when IsUseJoint equals 0.
    *	@param tcp : Target TCP name, invalid when IsUseJoint equals 1, "TCP" is valid as default
    *	@param ucs : Target UCS name, invalid when IsUseJoint equals 1, "Base" is valid as default
    *	@param speed : Motion speed, mm/s or °/s
    *	@param Acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_WayPoint(self, boxID, rbtID, type, points, RawACSpoints, tcp, ucs, speed, Acc, radius, isJoint, isSeek,
                      bit, state, cmdID):
        result = []
        command = 'WayPoint,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(points[i]) + ','
        for i in range(0, 6):
            command += str(RawACSpoints[i]) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(speed) + ','
        command += str(Acc) + ','
        command += str(radius) + ','
        command += str(type) + ','
        command += str(isJoint) + ','
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 11
    *	@param brief: Start waypoint move.
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param type : Move type, 0 for MoveJ, 1 for MoveL
    *	@param points : Target pose, invalid when IsUseJoint equals 1. Target joint positions is obtained through inversely solving from this pose when IsUseJoint equals 0
    *	@param RawACSpoints : Target joint positions when IsUseJoint equals 1; Reference joint positions for the inversely solving when IsUseJoint equals 0.
    *	@param tcp : Target TCP name, invalid when IsUseJoint equals 1, "TCP" is valid as default
    *	@param ucs : Target UCS name, invalid when IsUseJoint equals 1, "Base" is valid as default
    *	@param speed : Motion speed, mm/s or °/s
    *	@param Acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_WayPoint_nJ(self, boxID, rbtID, type, points, RawACSpoints, tcp, ucs, speed, Acc, radius, isJoint, isSeek,
                      bit, state, cmdID):
        result = []
        command = 'WayPoint,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(points[i]) + ','
        for i in range(0, len(RawACSpoints)):
            command += str(RawACSpoints[i]) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(speed) + ','
        command += str(Acc) + ','
        command += str(radius) + ','
        command += str(type) + ','
        command += str(isJoint) + ','
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Start waypoint move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param type : Move type, 0 for MoveJ, 1 for MoveL, 2 for MoveC
    *	@param EndPos : Target pose, invalid when IsUseJoint equals 1. Target pose is obtained through inverse kinematics from this pose when IsUseJoint equals 0
    *	@param AuxPos : Target auxiliary pose invalid when IsUseJoint equals 1, used as the middle point when nMoveType equals 2. Target pose is obtained through inverse kinematics from this pose when IsUseJoint equals 0
    *	@param AcsPos : Target joint positions when IsUseJoint equals 1; Reference joint positions for the inverse kinematics when IsUseJoint equals 0.
    *	@param Tcp : Target TCP name, invalid when IsUseJoint equals 1, "TCP" is valid as default
    *	@param Ucs : Target UCS name, invalid when IsUseJoint equals 1, "Base" is valid as default
    *	@param Vel : Motion speed, mm/s or °/s
    *	@param Acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param Radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_WayPoint2(self, boxID, rbtID, type, EndPos, AuxPos, AcsPos, Tcp, Ucs, Vel, Acc, Radius, isJoint, isSeek,
                       bit, state, cmdID):
        result = []
        command = 'WayPoint2,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(EndPos[i]) + ','
        for i in range(0, 6):
            command += str(AcsPos[i]) + ','
        command += Tcp + ','
        command += Ucs + ','
        command += str(Vel) + ','
        command += str(Acc) + ','
        command += str(Radius) + ','
        command += str(type) + ','
        command += str(isJoint) + ','
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        for i in range(0, 6):
            command += str(AuxPos[i]) + ','
        command += cmdID + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 13
    *	@param brief: Start waypoint move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param type : Move type, 0 for MoveJ, 1 for MoveL, 2 for MoveC
    *	@param EndPos : Target pose, invalid when IsUseJoint equals 1. Target pose is obtained through inverse kinematics from this pose when IsUseJoint equals 0
    *	@param AuxPos : Target auxiliary pose invalid when IsUseJoint equals 1, used as the middle point when nMoveType equals 2. Target pose is obtained through inverse kinematics from this pose when IsUseJoint equals 0
    *	@param AcsPos : Target joint positions when IsUseJoint equals 1; Reference joint positions for the inverse kinematics when IsUseJoint equals 0.
    *	@param Tcp : Target TCP name, invalid when IsUseJoint equals 1, "TCP" is valid as default
    *	@param Ucs : Target UCS name, invalid when IsUseJoint equals 1, "Base" is valid as default
    *	@param Vel : Motion speed, mm/s or °/s
    *	@param Acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param Radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_WayPoint2_nJ(self, boxID, rbtID, type, EndPos, AuxPos, AcsPos, Tcp, Ucs, Vel, Acc, Radius, isJoint, isSeek,
                       bit, state, cmdID):
        result = []
        command = 'WayPoint2,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(EndPos[i]) + ','
        for i in range(0, len(AcsPos)):
            command += str(AcsPos[i]) + ','
        command += Tcp + ','
        command += Ucs + ','
        command += str(Vel) + ','
        command += str(Acc) + ','
        command += str(Radius) + ','
        command += str(type) + ','
        command += str(isJoint) + ','
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        for i in range(0, 6):
            command += str(AuxPos[i]) + ','
        command += cmdID + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 14
    *	@param brief: Start joint move. HRIF_WayPoint is more recommended yet
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param points : Target pose, invalid when IsUseJoint equals 1. Target joint positions is obtained through inversely solving from this pose when IsUseJoint equals 0
    *	@param RawACSpoints : Target joint positions when IsUseJoint equals 1; Reference joint positions for the inversely solving when IsUseJoint equals 0.
    *	@param tcp : Target TCP name, invalid when IsUseJoint equals 1, "TCP" is valid as default
    *	@param ucs :Target UCS name, invalid when IsUseJoint equals 1, "Base" is valid as default
    *	@param speed : Motion speed, mm/s or °/s
    *	@param Acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveJ(self, boxID, rbtID, points, RawACSpoints, tcp, ucs, speed, Acc, radius, isJoint, isSeek, bit, state,
                   cmdID):
        result = []
        command = 'WayPoint,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(points[i]) + ','
        for i in range(0, 6):
            command += str(RawACSpoints[i]) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(speed) + ','
        command += str(Acc) + ','
        command += str(radius) + ','
        command += '0,'
        command += str(isJoint) + ','
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 14
    *	@param brief: Start joint move. HRIF_WayPoint is more recommended yet
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param points : Target pose, invalid when IsUseJoint equals 1. Target joint positions is obtained through inversely solving from this pose when IsUseJoint equals 0
    *	@param RawACSpoints : Target joint positions when IsUseJoint equals 1; Reference joint positions for the inversely solving when IsUseJoint equals 0.
    *	@param tcp : Target TCP name, invalid when IsUseJoint equals 1, "TCP" is valid as default
    *	@param ucs :Target UCS name, invalid when IsUseJoint equals 1, "Base" is valid as default
    *	@param speed : Motion speed, mm/s or °/s
    *	@param Acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveJ_nJ(self, boxID, rbtID, points, RawACSpoints, tcp, ucs, speed, Acc, radius, isJoint, isSeek, bit, state,
                   cmdID):
        result = []
        command = 'WayPoint,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(points[i]) + ','
        for i in range(0, len(RawACSpoints)):
            command += str(RawACSpoints[i]) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(speed) + ','
        command += str(Acc) + ','
        command += str(radius) + ','
        command += '0,'
        command += str(isJoint) + ','
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 15
    *	@param brief: Start linear move. HRIF_WayPoint is more recommended yet
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param points : Target pose
    *	@param RawACSpoints : Reference joint positions near to the target pose
    *	@param tcp : TCP name
    *	@param ucs : UCS name
    *	@param speed : Motion speed, mm/s or °/s
    *	@param Acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveL(self, boxID, rbtID, points, RawACSpoints, tcp, ucs, speed, Acc, radius, isSeek, bit, state, cmdID):
        result = []
        command = 'WayPoint,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(points[i]) + ','
        for i in range(0, 6):
            command += str(RawACSpoints[i]) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(speed) + ','
        command += str(Acc) + ','
        command += str(radius) + ','
        command += '1,'
        command += '0,'
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 16
    *	@param brief: Start linear move. HRIF_WayPoint is more recommended yet
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param points : Target pose
    *	@param RawACSpoints : Reference joint positions near to the target pose
    *	@param tcp : TCP name
    *	@param ucs : UCS name
    *	@param speed : Motion speed, mm/s or °/s
    *	@param Acc : Motion acceleration, mm/(s^2) or °/(s^2)
    *	@param radius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveL_nJ(self, boxID, rbtID, points, RawACSpoints, tcp, ucs, speed, Acc, radius, isSeek, bit, state, cmdID):
        result = []
        command = 'WayPoint,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(points[i]) + ','
        for i in range(0, len(RawACSpoints)):
            command += str(RawACSpoints[i]) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(speed) + ','
        command += str(Acc) + ','
        command += str(radius) + ','
        command += '1,'
        command += '0,'
        command += str(isSeek) + ','
        command += str(bit) + ','
        command += str(state) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 17
    *	@param brief: Start round move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param StartPoint : Start pose
    *	@param AuxPoint : Via pose
    *	@param EndPoint : End pose
    *	@param fixedPosure : 0 for unfixed orientation, 1 for fixed orientation, 2 for newly added gradual orientation arc motion.  
    *                 
    *	@param nMoveCType : 1 for arc, 0 for circle 
    *	@param nRadLen : Invalid when nMoveCType equals 1; Circles when nMoveCType equals 0.
    *			        
    *	@param speed : Motion speed, mm/s
    *	@param Acc : Motion acceleration, mm/(s^2)
    *	@param radius : Blending radius, mm
    *	@param tcp : TCP name
    *	@param ucs : UCS name
    *	@param cmdID : Command ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveC(self, boxID, rbtID, StartPoint, AuxPoint, EndPoint, fixedPosure, nMoveCType, nRadLen, speed, Acc,
                   radius, tcp, ucs, cmdID):
        result = []
        command = 'MoveC,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(StartPoint[i]) + ','
        for i in range(0, 6):
            command += str(AuxPoint[i]) + ','
        for i in range(0, 6):
            command += str(EndPoint[i]) + ','
        command += str(fixedPosure) + ','
        command += str(nMoveCType) + ','
        command += str(nRadLen) + ','
        command += str(speed) + ','
        command += str(Acc) + ','
        command += str(radius) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 17
    *	@param brief: Start round move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param StartPoint : Start pose
    *	@param AuxPoint : Via pose
    *	@param EndPoint : End pose
    *	@param joint : expand axis pose
    *	@param fixedPosure : 0 for unfixed orientation, 1 for fixed orientation, 2 for newly added gradual orientation arc motion 
    *                    
    *	@param nMoveCType : 1 for arc, 0 for circle
    *	@param nRadLen : Invalid when nMoveCType equals 1; Circles when nMoveCType equals 0
    *			         
    *	@param speed : Motion speed, mm/s
    *	@param Acc : Motion acceleration, mm/(s^2)
    *	@param radius : Blending radius, mm
    *	@param tcp : UCS name
    *	@param ucs : TCP name
    *	@param cmdID: Command ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveC_nJ(self, boxID, rbtID, StartPoint, AuxPoint, EndPoint, joint, IsUseCurRefAC, fixedPosure, nMoveCType,
                      nRadLen, speed, Acc, radius, tcp, ucs, cmdID):
        result = []
        command = 'MoveC,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(StartPoint[i]) + ','
        for i in range(0, 6):
            command += str(AuxPoint[i]) + ','
        for i in range(0, 6):
            command += str(EndPoint[i]) + ','
        for i in range(0, len(joint)):
            command += str(joint[i]) + ','
        command += str(IsUseCurRefAC) + ','
        command += str(fixedPosure) + ','
        command += str(nMoveCType) + ','
        command += str(nRadLen) + ','
        command += str(speed) + ','
        command += str(Acc) + ','
        command += str(radius) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 18
    *	@brief: Start zigzag move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param StartPoint : Start pose
    *	@param EndPoint : End pose
    *	@param PlanePoint : Plane pose
    *	@param Speed : Motion speed, mm/s
    *	@param Acc : Motion acceleration, mm/(s^2)
    *	@param WIdth : Width
    *	@param Density : Density, mm
    *	@param EnableDensity : 0 is disable density and 1 for enable density
    *	@param EnablePlane : Use plane pose or not; UCS is automatically used if plane pose is not used
    *	@param EnableWaiTime : 0 for disable waiting time, 1 for enable waiting time
    *	@param PosiTime : Waiting time (ms) for Positive turning point
    *	@param NegaTime : Waiting time (ms) for Negative turning point
    *	@param Radius : Blending radius, mm
    *	@param tcp : TCP name
    *	@param ucs : UCS name
    *	@param cmdID : Command ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_MoveZ(self, boxID, rbtID, StartPoint, EndPoint, PlanePoint, Speed, Acc, WIdth, Density, EnableDensity,
                   EnablePlane, EnableWaiTime, PosiTime, NegaTime, Radius, tcp, ucs, cmdID):
        result = []
        command = 'MoveZ,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(StartPoint[i]) + ','
        for i in range(0, 6):
            command += str(EndPoint[i]) + ','
        for i in range(0, 6):
            command += str(PlanePoint[i]) + ','
        command += str(Speed) + ','
        command += str(Acc) + ','
        command += str(WIdth) + ','
        command += str(Density) + ','
        command += str(EnableDensity) + ','
        command += str(EnablePlane) + ','
        command += str(EnableWaiTime) + ','
        command += str(PosiTime) + ','
        command += str(NegaTime) + ','
        command += str(Radius) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 19
    *	@brief: Start elliptical move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dP1 : Teaching p1 (p1~p5 should be listed as sequence in arc)
    *	@param dP2 : Teaching p2
    *	@param dP3 : Teaching p3
    *	@param dP4 : Teaching p4
    *	@param dP5 : Teaching p5
    *	@param nOrientMode : 0 is for arc, 1 is for circle
    *	@param nMoveType : 0 for unfixed orientation , 1 for fixed orientation
    *	@param dArcLength : Arc length (mm)
    *	@param dVelocity : Motion speed, mm/s
    *	@param dAcc : Motion acceleration, mm/(s^2)
    *	@param Radius : Blending radius, mm
    *	@param tcp : TCP name
    *	@param ucs : UCS name
    *	@param cmdID : Command ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveE(self, boxID, rbtID, dP1, dP2, dP3, dP4, dP5, nOrientMode, nMoveType, dArcLength, dVelocity, dAcc,
                   Radius, tcp, ucs, cmdID):
        result = []
        command = 'MoveE,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(dP1[i]) + ','
        for i in range(0, 6):
            command += str(dP2[i]) + ','
        for i in range(0, 6):
            command += str(dP3[i]) + ','
        for i in range(0, 6):
            command += str(dP4[i]) + ','
        for i in range(0, 6):
            command += str(dP5[i]) + ','
        command += str(nOrientMode) + ','
        command += str(nMoveType) + ','
        command += str(dArcLength) + ','
        command += str(dVelocity) + ','
        command += str(dAcc) + ','
        command += str(Radius) + ','
        command += str(tcp) + ','
        command += str(ucs) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 20
    *	@brief: Start spiral move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dSpiralIncrement : Spiral Increment radius
    *	@param dSpiralDiameter : Spiral end radius
    *	@param dVelocity : Motion speed, mm/s
    *	@param dAcc : Motion acceleration, mm/(s^2)
    *	@param dRadius : Blending radius, mm
    *	@param sTcpName : TCP name
    *	@param sUcsName : UCS name
    *	@param cmdID : Command ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveS(self, boxID, rbtID, dSpiralIncrement, dSpiralDiameter, dVelocity, dAcc, dRadius, sTcpName, sUcsName,
                   cmdID):
        result = []
        command = 'MoveS,'
        command += str(rbtID) + ','
        command += str(dSpiralIncrement) + ','
        command += str(dSpiralDiameter) + ','
        command += str(dVelocity) + ','
        command += str(dAcc) + ','
        command += str(dRadius) + ','
        command += str(sTcpName) + ','
        command += str(sUcsName) + ','
        command += str(cmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 21
    *	@brief: Start relative joint move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nAxis: Axis ID , 0~5 for jonit 1 ~6
    *	@param nDirection: Move direction, 0 for negative,1 for positive
    *	@param dDistance: Move distance (°)
    '''
    def HRIF_MoveRelJ(self, boxID, rbtID, nAxis, nDirection, dDistance):
        result = []
        command = 'MoveRelJ,'
        command += str(rbtID) + ','
        command += str(nAxis) + ','
        command += str(nDirection) + ','
        command += str(dDistance) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 22
    *	@brief: Start relative linear move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nAxis: Pose ID, 0~5 for X, Y, Z, Rx, Ry, Rz
    *	@param nDirection: Move direction, 0 for negative, 1 for positive
    *	@param dDistance: Move distance (mm or °)
    *   @param nToolMotion: Tool motion, 0 for UCS based move, 1 for TCP based move
    '''
    def HRIF_MoveRelL(self, boxID, rbtID, nAxis, nDirection, dDistance, nToolMotion):
        result = []
        command = 'MoveRelL,'
        command += str(rbtID) + ','
        command += str(nAxis) + ','
        command += str(nDirection) + ','
        command += str(dDistance) + ','
        command += str(nToolMotion) + ','
        command += ';'
        # print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 23
    *	@brief: Start relative wayPoint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nType : Move type, 0 for joint, 1 for linear
    *	@param nPointList : Using point saved in points list or not, 0 for not using,  1 for using
    *	@param Pos : Target pose
    *   @param rawACT : Target joint positions
    *   @param nrelMoveType : Relative move type, 0 for absolute value, 1 for superimposed value
    *   @param nAxisMask : Is Axis/Direction Moving, 0 for not moving, 1 for moving
    *   @param dTarget : Moving distance; invalid when nAxisMask equals 0; joint move an absolute or superimposed distance when nAxisMask equals 1 and nType equals 0; Pose move an absolute or superimposed distance when nAxisMask equals 1 and nType equals 1
    *   @param sTcpName : Target TCP name
    *   @param sUcsName : Target UCS name
    *   @param dVelocity : Velocity (mm/s) or (°/s)
    *   @param dAcc : Acceleration (mm/s^2) or (°/s^2)
    *   @param dRadius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    '''
    def HRIF_WayPointRel(self, boxID, rbtID, nType, nPointList, Pos, rawACT, nrelMoveType, nAxisMask, dTarget, sTcpName,
                         sUcsName, dVelocity, dAcc, dRadius, nIsUseJoint, nIsSeek, nIOBit, nIOState, strcmdID):
        result = []
        command = 'WayPointRel,'
        command += str(rbtID) + ','
        command += str(nType) + ','
        command += str(nPointList) + ','

        for i in range(0, 6):
            command += str(Pos[i]) + ','

        for i in range(0, 6):
            command += str(rawACT[i]) + ','

        command += str(nrelMoveType) + ','

        for i in range(0, 6):
            command += str(nAxisMask[i]) + ','

        for i in range(0, 6):
            command += str(dTarget[i]) + ','

        command += str(sTcpName) + ','
        command += str(sUcsName) + ','
        command += str(dVelocity) + ','
        command += str(dAcc) + ','
        command += str(dRadius) + ','
        command += str(nIsUseJoint) + ','
        command += str(nIsSeek) + ','
        command += str(nIOBit) + ','
        command += str(nIOState) + ','
        command += str(strcmdID) + ',;'
        # print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 24
    *	@brief: Start relative wayPoint
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nType : Move type, 0 for joint, 1 for linear
    *	@param nPointList : Using point saved in points list or not, 0 for not using,  1 for using
    *	@param Pos : Target pose
    *   @param rawACT : Target joint positions
    *   @param nrelMoveType : Relative move type, 0 for absolute value, 1 for superimposed value
    *   @param nAxisMask : Is Axis/Direction Moving, 0 for not moving, 1 for moving
    *   @param dTarget : Moving distance; invalid when nAxisMask equals 0; joint move an absolute or superimposed distance when nAxisMask equals 1 and nType equals 0; Pose move an absolute or superimposed distance when nAxisMask equals 1 and nType equals 1
    *   @param sTcpName : Target TCP name
    *   @param sUcsName : Target UCS name
    *   @param dVelocity : Velocity (mm/s) or (°/s)
    *   @param dAcc : Acceleration (mm/s^2) or (°/s^2)
    *   @param dRadius : Blending radius, mm
    *	@param isJoint : Using joint or not, usable when MoveType equals 0, 0 for not using joint, 1 for using joint
    *	@param isSeek,bit,state: Seeking or not, 1 for seeking; Motion stops when DO-nIOBit equals nIoState
    *	@param cmdID: Command ID, waypoint ID also, customized or set to 1, 2, 3 in order
    '''
    def HRIF_WayPointRel_nJ(self, boxID, rbtID, nType, nPointList, Pos, rawACT, nrelMoveType, nAxisMask, dTarget, sTcpName,
                         sUcsName, dVelocity, dAcc, dRadius, nIsUseJoint, nIsSeek, nIOBit, nIOState, strcmdID):
        result = []
        command = 'WayPointRel,'
        command += str(rbtID) + ','
        command += str(nType) + ','
        command += str(nPointList) + ','

        for i in range(0, 6):
            command += str(Pos[i]) + ','

        for i in range(0, len(rawACT)):
            command += str(rawACT[i]) + ','

        command += str(nrelMoveType) + ','

        for i in range(0, 6):
            command += str(nAxisMask[i]) + ','

        for i in range(0, 6):
            command += str(dTarget[i]) + ','

        command += str(sTcpName) + ','
        command += str(sUcsName) + ','
        command += str(dVelocity) + ','
        command += str(dAcc) + ','
        command += str(dRadius) + ','
        command += str(nIsUseJoint) + ','
        command += str(nIsSeek) + ','
        command += str(nIOBit) + ','
        command += str(nIOState) + ','
        command += str(strcmdID) + ',;'
        # print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 25
    *	@brief: Check temperature under low
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0]: 1 as under low, 0 as not under low
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_CheckTemperatureUnderLow(self, boxID, rbtID, result):
        command = 'CheckTemperatureUnderLow,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 26
    *	@brief: Start linear weave move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param StartPoint : Start pose
    *	@param EndPoint : End pose
    *	@param dVelocity : Motion speed, mm/s
    *	@param Acc : Motion acceleration, mm/(s^2)
    *	@param dRadius : Blending radius, mm
    *	@param dAmplitude : Weaving amplitude, mm
    *	@param dIntervalDistance : Referenced weaving interval, robot will rectify it slightly to ensure the StartPos and EndPos be passed through after some weaving cycles, mm 
    *                           
    *	@param nWeaveFrameType : the way to determine the weaving plane and weaving direction
    *                            0: The +X of weaving plane is from StartPos to EndPos. The +Z(normal direction) of weaving plane is along TCP +Z. The +Y of weaving plane is determined by +X and +Z. The start direction of weaving move is toward the +Y side
    *                            1: The +X of weaving plane is from StartPos to EndPos. The Z of weaving plane is parallel with TCP Z. The +Y of weaving plane is along TCP +Y. The start direction of weaving move is toward the +Y side                              
    *	@param dElevation : The elevation of the weave, degree
    *	@param dAzimuth : The azimuth of the weave, degree
    *	@param dCentreRise : The bulge height of the welding torch at the weaving weld center, mm
    *   @param nEnableWaiTime : 0 to disable waiting time, 1 to enable waiting time
    *	@param nPosiTime : Waiting time (ms) at Positive turning point
    *	@param nNegaTime : Waiting time (ms) at Negative turning point
    *	@param sTcpName : TCP name
    *	@param sUcsName : UCS name
    *	@param sCmdID : Command ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MoveLinearWeave(self, boxID, rbtID, StartPoint, EndPoint, dVelocity, Acc, dRadius, dAmplitude,
                             dIntervalDistance, nWeaveFrameType,
                             dElevation, dAzimuth, dCentreRise, nEnableWaiTime, nPosiTime, nNegaTime, sTcpName,
                             sUcsName, sCmdID, result):
        command = 'MoveLinearWeave,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(StartPoint[i]) + ','
        for i in range(0, 6):
            command += str(EndPoint[i]) + ','
        command += str(dVelocity) + ','
        command += str(Acc) + ','
        command += str(dRadius) + ','
        command += str(dAmplitude) + ','
        command += str(dIntervalDistance) + ','
        command += str(nWeaveFrameType) + ','
        command += str(dElevation) + ','
        command += str(dAzimuth) + ','
        command += str(dCentreRise) + ','
        command += str(nEnableWaiTime) + ','
        command += str(nPosiTime) + ','
        command += str(nNegaTime) + ','
        command += str(sTcpName) + ','
        command += str(sUcsName) + ','
        command += str(sCmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 27
    *	@brief: circular weave move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param StartPoint : Start pose
    *	@param AuxPoint : Via pose
    *	@param EndPoint : End pose
    *	@param dVelocity : Motion speed, mm/s
    *	@param Acc : Motion acceleration, mm/(s^2)
    *	@param dRadius : Blending radius, mm
    *	@param nOrientMode : 0 for unfixed orientation, 1 for fixed orientation
    *	@param nMoveWhole : 0: 0 for circle, 1 for arc
    *	@param dMoveWholeLen :Invalid when nMoveCType equals 1; Circles when nMoveCType equals 0.
    *	@param dAmplitude : Amplitude, mm
    *	@param dIntervalDistance :Referenced weaving interval, robot will rectify it slightly to ensure the StartPos and EndPos be passed through after some weaving cycles, mm 
    *	@param nWeaveFrameType : the way to determine the weaving plane and weaving direction
    *                            0: The +X of weaving plane is from StartPos to EndPos. The +Z(normal direction) of weaving plane is along TCP +Z. The +Y of weaving plane is determined by +X and +Z. The start direction of weaving move is toward the +Y side
    *                            1: The +X of weaving plane is from StartPos to EndPos. The Z of weaving plane is parallel with TCP Z. The +Y of weaving plane is along TCP +Y. The start direction of weaving move is toward the +Y side                             
    *	@param dElevation : The elevation of the weave, degree
    *	@param dAzimuth : The azimuth of the weave, degree
    *	@param dCentreRise : The bulge height of the welding torch at the weaving weld center, mm
    *   @param nEnableWaiTime : 0 to disable waiting time, 1 to enable waiting time
    *	@param nPosiTime : Waiting time (ms) at Positive turning point
    *	@param nNegaTime : Waiting time (ms) at Negative turning point
    *	@param sTcpName : TCP name
    *	@param sUcsName : UCS name
    *	@param sCmdID : Command ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_MoveCircularWeave(self, boxID, rbtID, StartPoint, AuxPoint, EndPoint, dVelocity, Acc, dRadius, nOrientMode,
                               nMoveWhole, dMoveWholeLen, dAmplitude, dIntervalDistance, nWeaveFrameType,
                               dElevation, dAzimuth, dCentreRise, nEnableWaiTime, nPosiTime, nNegaTime, sTcpName,
                               sUcsName, sCmdID, result):
        command = 'MoveCircularWeave,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(StartPoint[i]) + ','
        for i in range(0, 6):
            command += str(AuxPoint[i]) + ','
        for i in range(0, 6):
            command += str(EndPoint[i]) + ','
        command += str(dVelocity) + ','
        command += str(Acc) + ','
        command += str(dRadius) + ','
        command += str(nOrientMode) + ','
        command += str(nMoveWhole) + ','
        command += str(dMoveWholeLen) + ','
        command += str(dAmplitude) + ','
        command += str(dIntervalDistance) + ','
        command += str(nWeaveFrameType) + ','
        command += str(dElevation) + ','
        command += str(dAzimuth) + ','
        command += str(dCentreRise) + ','
        command += str(nEnableWaiTime) + ','
        command += str(nPosiTime) + ','
        command += str(nNegaTime) + ','
        command += str(sTcpName) + ','
        command += str(sUcsName) + ','
        command += str(sCmdID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 11 Interface of Trajectory Motion Control
    #
    '''
    *	@index : 1
    *	@param brief: Start to push ACS points for MovePathJ
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathJ name
    *	@param speedRatio : Speed override
    *	@param radius : Blending radius, mm
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_StartPushMovePathJ(self, boxID, rbtID, trackName, speedRatio, radius):
        result = []
        command = 'StartPushMovePath,'
        command += str(rbtID) + ','
        command += trackName + ','
        command += str(speedRatio) + ','
        command += str(radius) + ','
        command += ';'
        # print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Push an ACS raw point to MovePathJ. 4 points at lease are needed.
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathJ name
    *	@param paramsJ[0]-paramsJ[5] : joint positions
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PushMovePathJ(self, boxID, rbtID, trackName, paramsJ):
        result = []
        command = 'PushMovePathJ,'
        command += str(rbtID) + ','
        command += trackName
        command += ','
        for i in range(0, 6):
            command += str(paramsJ[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: End pushing ACS raw point to MovePathJ and start calculating the path
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathJ name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_EndPushMovePathJ(self, boxID, rbtID, trackName):
        result = []
        command = 'EndPushMovePath,'
        command += str(rbtID) + ','
        command += trackName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: End pushing PCS raw point to MovePathL and start calculating the path
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathL name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_EndPushMovePath(self, boxID, rbtID, trackName):
        result = []
        command = 'EndPushMovePath,'
        command += str(rbtID) + ','
        command += trackName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    # '''
    # *	@index : 5
    # *	@param brief:
    # *	@param boxID: Control box ID
    # *	@param rbtID: Robot ID
    # *	@param trackName :
    # *	
    # *	@return : nRet=0 : Function call succeeded
    # *             nRet>0 : Error code of function call
    # '''
    # def HRIF_MovePath(self,boxID,rbtID,trajectName):
    #     result = []
    #     command = 'MovePath,'
    #     command += str(rbtID) + ','
    #     command += str(trajectName) + ','
    #     command += ';'
    #     return self.g_clients[boxID].sendAndRecv(command,result)

    '''
    *	@index : 5
    *	@param brief: Run PathJ
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_MovePathJ(self, boxID, rbtID, sPathName):
        result = []
        command = 'MovePathJ,'
        command += str(rbtID) + ','
        command += str(sPathName) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Read the status of the path
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : Path name
    *	@param result[0] : State of path
    *               0: Not taught 
    *               1: Teaching in progress
    *               2: Calculating
    *               3: Calculation completed
    *               4: Teaching completed
    *               5:Calculation error
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadMovePathJState(self, boxID, rbtID, trackName, result):
        command = 'ReadMovePathState,'
        command += str(rbtID) + ','
        command += trackName + ','
        command += ';'
        retData = self.g_clients[boxID].sendAndRecv(command, result)
        return retData

    '''
    *	@index : 7
    *	@param brief: Update MovePathJ name
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathJ name
    *	@param newName : New MovePathJ name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_UpdateMovePathJName(self, boxID, rbtID, trackName, newName):
        result = []
        command = 'UpdateMovePathName,'
        command += str(rbtID) + ','
        command += trackName + ','
        command += newName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 8
    *	@param brief: Delete a MovepathJ
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathJ name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_DelMovePathJ(self, boxID, rbtID, trackName):
        result = []
        command = 'DelMovePath,'
        command += str(rbtID) + ','
        command += trackName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 9
    *	@param brief: Read process and point index of a path move
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param result[0] : Current path process, 0~1, more than 0.999999 for move done
    *   @param result[1] : Point index finished
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadTrackProcess(self, boxID, rbtID, result):
        command = 'ReadSoftMotionProgress,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 10
    *	@param brief: Initialize MovePathL
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathL name
    *	@param vel : Velocity
    *	@param acc : Acceleration
    *	@param jerk : Jerk
    *	@param ucs : UCS name
    *	@param tcp : TCP name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_InitMovePathL(self, boxID, rbtID, trackName, vel, acc, jerk, ucs, tcp):
        result = []
        command = 'InitMovePathL,'
        command += str(rbtID) + ','
        command += trackName + ','
        command += str(vel) + ','
        command += str(acc) + ','
        command += str(jerk) + ','
        command += ucs + ','
        command += tcp + ','
        command += ';'
        # print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 11
    *	@param brief: Push an PCS point to MovePathL
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathL name
    *	@param paramPcs : Raw point pose
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PushMovePathL(self, boxID, rbtID, trackName, paramPcs):
        result = []
        command = 'PushMovePathL,'
        command += str(rbtID) + ','
        command += trackName + ','
        for i in range(0, 6):
            command += str(paramPcs[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 12
    *	@param brief: Push an list of ACS or PCS points to MovePathJ or MovePathL
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param trackName : MovePathJ or MovePathL name
    *	@param moveType : Move type, 0 for MovePathJ, 1 for MovePathL
    *	@param pointsSize : Points number
    *	@param points : Points list
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PushMovePaths(self, boxID, rbtID, trackName, moveType, pointsSize, points):
        result = []
        command = 'PushMovePaths,'
        command += str(rbtID) + ','
        command += trackName
        command += ','
        command += str(moveType)
        command += ','
        command += str(pointsSize)
        command += ','
        for pos in points:
            command += str(pos) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 13
    *	@param brief: Run PathL
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MovePathL(self, boxID, rbtID, sPathName):
        result = []
        command = 'MovePathL,'
        command += str(rbtID) + ','
        command += str(sPathName) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 14
    *	@param brief: Set Override for MovePathL
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param MovePathOverride : Set Override
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMovePathOverride(self, boxID, rbtID, MovePathOverride):
        result = []
        command = 'SetMovePathOverride,'
        command += str(rbtID) + ','
        command += str(MovePathOverride)
        command += ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 15
    *	@param brief: Initialize path
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *   @param nRawDataType: Raw points data type, 0 for ACS, 1 for PCS
    *	@param sPathName : Path name
    *	@param vel : Velocity for PathL calculation
    *	@param acc : Acceleration for PathL calculation
    *	@param jerk : Jerk for PathL calculation
    *	@param ucs : UCS name
    *	@param tcp : TCP name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_InitPath(self, boxID, rbtID, nRawDataType, sPathName, dSpeedRatio, dRadius, vel, acc, jerk, ucs, tcp):
        result = []
        command = 'InitPath,'
        command += str(rbtID) + ','
        command += str(nRawDataType) + ','
        command += sPathName + ','
        command += str(dSpeedRatio) + ','
        command += str(dRadius) + ','
        command += str(vel) + ','
        command += str(acc) + ','
        command += str(jerk) + ','
        command += ucs + ','
        command += tcp + ','
        command += ';'
        # print(command)
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 16
    *	@param brief: Push raw points to path
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	@param sPoints : Points data
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PushPathPoints(self, boxID, rbtID, sPathName, sPoints):
        result = []
        command = 'PushPathPoints,'
        command += str(rbtID) + ','
        command += sPathName
        command += ','
        for pos in sPoints:
            command += str(pos) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 17
    *	@param brief: End pushing points to the path and start calculating the pathJ/L
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_EndPushPathPoints(self, boxID, rbtID, sPathName):
        result = []
        command = 'EndPushPathPoints,'
        command += str(rbtID) + ','
        command += sPathName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 18
    *	@param brief: Delete the Path with the specified name
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_DelPath(self, boxID, rbtID, sPathName):
        result = []
        command = 'DelPath,'
        command += str(rbtID) + ','
        command += sPathName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 19
    *	@param brief: Read all path lists
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result: path name list
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadPathList(self, boxID, rbtID, result):
        command = 'ReadPath,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 20
    *	@param brief: Read the information of the specified name path
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	@param result[0] : Raw point type, 0 for ACS, 1 for PCS
    *	@param result[1] : PathJ status:
    *                      0: Not taught, 1: Teaching in progress, 4: Teaching completed, 2: Calculating, 5: Calculation error, 3: Calculation completed, 9: Imported, 10: Post-import processing 
    *	@param result[2] : PathJ error code
    *	@param result[3] : The state of PathL, the same as stateJ
    *	@param result[4] : PathL error code
    *	@param result[5] : Path speed ratio
    *	@param result[6] : Blending radius, mm
    *	@param result[7] : Velocity for Path
    *	@param result[8] : Acceleration for Path
    *	@param result[9] : Jerk for Path
    *	@param result[10] : User coordinates
    *	@param result[11] : Tool coordinates
    *	@param result[12] : Raw points count
    *	@param result[13] : The first raw point coordinates (J1/J2/J3/J4/J5/J6 or X/Y/Z/RX/RY/RZ)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadPathInfo(self, boxID, rbtID, sPathName, result):
        command = 'ReadPath,'
        command += str(rbtID) + ','
        command += sPathName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 21
    *	@param brief: Update the name of the specified path
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	@param sPathNewName : New path name
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_UpdatePathName(self, boxID, rbtID, sPathName, sPathNewName):
        result = []
        command = 'UpdatePathName,'
        command += str(rbtID) + ','
        command += sPathName + ','
        command += sPathNewName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 22
    *	@param brief: Read the status of the path
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	@param result[0] : State of MovePathJ refer to HRIF_ReadPathInfo
    *	@param result[1] : nErrorCodeJ
    *	@param result[2] : State of MovePathL refer to HRIF_ReadPathInfo
    *	@param result[3] : nErrorCodeL
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadPathState(self, boxID, rbtID, sPathName, result):
        command = 'ReadPathState,'
        command += str(rbtID) + ','
        command += sPathName + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 23
    *	@param brief: Set the reference joint coordinates for space point trajectory
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param sPathName : Path name
    *	@param dAcs : Reference joint coordinates
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetPathRefJoints(self, boxID, rbtID, sPathName,dAcs):
        command = 'SetPathRefJoints,'
        command += str(rbtID) + ','
        command += sPathName + ','
        for i in range(6):
            command += str(dAcs[i]) + ','
        command += ';'
        print(command)
        result = []
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 24
    *	@param brief: Start MovePathJ for online implementation planning
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dVel : Joint velocitie
    *   @param dAcc : Joint acceleration
    *   @param dTol : Filter parameter
    *	@param RawACSpoints : Target joint pose
    *	@param nIsSetIO : Is set IO, 0 as set, 1 as not set
    *	@param nEndDOMask : The EndDO to be modified is identified by bit
    *	@param nEndDOVal : The target state of each EndDO to be modified
    *	@param nBoxDOMask : The BoxDO to be modified is identified by bit
    *	@param nBoxDOVal : The target state of each BoxDO to be modified
    *	@param nBoxCOMask : The BoxCO to be modified is identified by bit
    *	@param nBoxCOVal : The target state of each BoxCO to be modified
    *	@param nBoxAOCH0_Mask : Indicator of whether BoxAOCH0 needs to be modified
    *	@param nBoxAOCH0_Mode : Mode
    *	@param nBoxAOCH1_Mask : Indicator of whether BoxAOCH1 needs to be modified
    *	@param nBoxAOCH1_Mode : Mode
    *	@param dbBoxAOCH0_Val : Corresponding analog value
    *	@param dbBoxAOCH1_Val : Corresponding analog value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_MovePathJOL(self, boxID, rbtID, dVel, dAcc, dTol, RawACSpoints, nIsSetIO, nEndDOMask, nEndDOVal,
                         nBoxDOMask, nBoxDOVal, nBoxCOMask, nBoxCOVal, nBoxAOCH0_Mask, nBoxAOCH0_Mode, nBoxAOCH1_Mask,
                         nBoxAOCH1_Mode, dbBoxAOCH0_Val, dbBoxAOCH1_Val):
        result = []
        command = 'MovePathJOL,'
        command += str(rbtID) + ','
        command += str(dVel) + ','
        command += str(dAcc) + ','
        command += str(dTol) + ','
        for i in range(0, len(nIsSetIO)):
            for j in range(6*i, 6*i+6):
                command += str(RawACSpoints[j]) + ','
            command += str(nIsSetIO[i]) + ','
            command += str(nEndDOMask[i]) + ','
            command += str(nEndDOVal[i]) + ','
            command += str(nBoxDOMask[i]) + ','
            command += str(nBoxDOVal[i]) + ','
            command += str(nBoxCOMask[i]) + ','
            command += str(nBoxCOVal[i]) + ','
            command += str(nBoxAOCH0_Mask[i]) + ','
            command += str(nBoxAOCH0_Mode[i]) + ','
            command += str(nBoxAOCH1_Mask[i]) + ','
            command += str(nBoxAOCH1_Mode[i]) + ','
            command += str(dbBoxAOCH0_Val[i]) + ','
            command += str(dbBoxAOCH1_Val[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    '''
    *	@index : 25
    *	@param brief: Obtain the index number of the current point position of MovePathJOL motion and the total number of points in the trajectory motion
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dVel : Joint velocitie
    *   @param dAcc : Joint acceleration
    *   @param dTol : Filter parameter
    *	@param RawACSpoints : Target joint pose
    *	@param nIsSetIO : Is set IO, 0 as set, 1 as not set
    *	@param nEndDOMask : The EndDO to be modified is identified by bit
    *	@param nEndDOVal : The target state of each EndDO to be modified
    *	@param nBoxDOMask : The BoxDO to be modified is identified by bit
    *	@param nBoxDOVal : The target state of each BoxDO to be modified
    *	@param nBoxCOMask : The BoxCO to be modified is identified by bit
    *	@param nBoxCOVal : The target state of each BoxCO to be modified
    *	@param nBoxAOCH0_Mask : Indicator of whether BoxAOCH0 needs to be modified
    *	@param nBoxAOCH0_Mode : Mode
    *	@param nBoxAOCH1_Mask : Indicator of whether BoxAOCH1 needs to be modified
    *	@param nBoxAOCH1_Mode : Mode
    *	@param dbBoxAOCH0_Val : Corresponding analog value
    *	@param dbBoxAOCH1_Val : Corresponding analog value
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_GetMovePathJOLIndex(self, rbtID, boxID, result):
        command = 'GetMovePathJOLIndex,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)
    
    #
    # part 12 Interfaces for Servo
    #

    '''
    *	@index : 1
    *	@param brief:  Start Servo J/P with the specified ServoTime of update and LookaheadTime. This function is a member of the suite including HRIF_StartServo, HRIF_PushServoJ and HRIF_PushServoP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param servoTime : interval of update (s)
    *	@param lookaheadTime : LookaheadTime (s)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_StartServo(self, boxID, rbtID, servoTime, lookaheadTime):
        result = []
        command = 'StartServo,'
        command += str(rbtID) + ','
        command += str(servoTime) + ',' + str(lookaheadTime) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Push point of joint positions to robot with the ServoTime and LookaheadTime specified in HRIF_StartServo function, and the robot will track the joint positions in real time. This function is a member of the suite including HRIF_StartServo, HRIF_PushServoJ and HRIF_PushServoP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dACSd : Joint positions
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PushServoJ(self, boxID, rbtID, dACS):
        result = []
        command = 'PushServoJ,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(dACS[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Push pose point to robot with the ServoTime and LookaheadTime specified in HRIF_StartServo function, and the robot will track the pose in real time. This function is a member of the suite including HRIF_StartServo, HRIF_PushServoJ and HRIF_PushServoP
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param pose : Pose coordinates
    *	@param ucs : UCS coordinates
    *	@param tcp : TCP coordinates
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_PushServoP(self, boxID, rbtID, pose, ucs, tcp):
        result = []
        command = 'PushServoP,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(pose[i]) + ','
        for i in range(0, 6):
            command += str(ucs[i]) + ','
        for i in range(0, 6):
            command += str(tcp[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: In SpeedJ mode,Push joint command velocity
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param cmdVel : Joint speed
    *	@param acc : Joint Acc
    *	@param runtime : Command execution exceeds this time, the movement will stop
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SpeedJ(self, boxID, rbtID, cmdVel, acc, runtime):
        result = []
        command = 'SpeedJ,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(cmdVel[i]) + ','
        command += str(acc) + ','
        command += str(runtime) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: In SpeedL mode,Push position command velocity
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param cmdVel : Position velocity
    *	@param linearAcc :  Linear Acc
    *	@param acc : Angular Acc
    *	@param runtime : Command execution exceeds this time, the movement will stop
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SpeedL(self, boxID, rbtID, cmdVel, linearAcc, acc, runtime):
        result = []
        command = 'SpeedL,'
        command += str(rbtID) + ','
        for i in range(0, 6):
            command += str(cmdVel[i]) + ','
        command += str(linearAcc) + ','
        command += str(acc) + ','
        command += str(runtime) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Initialize servoEsJ, truncating points
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_InitServoEsJ(self, boxID, rbtID):
        result = []
        command = 'InitServoEsJ,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 7
    *	@param brief: Start move for servoEsJ
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dServoTime : interval of update (s)
    *	@param dLookaheadTime : LookaheadTime (s)
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_StartServoEsJ(self, boxID, rbtID, dServoTime, dLookaheadTime):
        result = []
        command = 'StartServoEsJ,'
        command += str(rbtID) + ','
        command += str(dServoTime) + ','
        command += str(dLookaheadTime) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 8
    *	@param brief: Push points list for servoEsJ
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nPointSize : Point size, maximum 500
    *	@param sPoints : Points list
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_PushServoEsJ(self, boxID, rbtID, nPointSize, sPoints):
        result = []
        command = 'PushServoEsJ,'
        command += str(rbtID) + ','
        command += str(nPointSize) + ','
        for i in range(len(sPoints)):
            command += str(sPoints[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 9
    *	@param brief: Read servoEsJ state with call interval more than 20 ms
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param result[0] : Pushing point is allowed or not; 0 for allowed, 1 for not allowed
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''

    def HRIF_ReadServoEsJState(self, boxID, rbtID, result):
        command = 'ReadServoEsJState,'
        command += str(rbtID) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 13 Interface of relative tracking motion
    #

    '''
    *	@index : 1
    *	@param brief: Set motion parameters of tracking motion
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param state : 0 to disable tracking, 1 to enable trackin
    *	@param distance : Relative distance of tracking
    *	@param dAwayVelocity: Away velocity of tracking
    *	@param dGobackVelocity: Back velocity of tracking
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMoveTraceParams(self, boxID, rbtID, state, distance, dAwayVelocity, dGobackVelocity):
        result = []
        command = 'SetMoveTraceParams,'
        command += str(rbtID) + ','
        command += str(state) + ','
        command += str(distance) + ','
        command += str(dAwayVelocity) + ','
        command += str(dGobackVelocity) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Set initial parameters of tracking motion
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dK,dB: parameters in equation as y = dK * x + dB
    *	@param maxLimit: Max distance detected by laser sensor
    *	@param minLinit: Min distance detected by laser sensor
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMoveTraceInitParams(self, boxID, rbtID, dK, dB, maxLimit, minLimit):
        result = []
        command = 'SetMoveTraceInitParams,'
        command += str(rbtID) + ','
        command += str(dK) + ','
        command += str(dB) + ','
        command += str(maxLimit) + ','
        command += str(minLimit) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief:  Set end orientation in tracking motion
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param direction: Tracking and exploration direction (x, y, z invalid, can be set to 0) (Rx, Ry, Rz units [°])
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetMoveTraceUcs(self, boxID, rbtID, direction):
        result = []
        command = 'SetMoveTraceUcs,'
        command += str(rbtID) + ','
        for i in range(len(direction)):
            command += str(direction[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Set tracking motion state
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param state: 0 to disable tracking, 1 to enable tracking
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetTrackingState(self, boxID, rbtID, state):
        result = []
        command = 'SetTrackingState,'
        command += str(rbtID) + ','
        command += str(state) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 14 interfaces for tracking position
    #
    '''
    *	@index : 1
    *	@param brief: Set max velocity of tracking position
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dMaxLineVel: Max follow position velocity
    *	@param dMaxOriVel: Max follow angular velocity
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetPoseTrackingMaxMotionLimit(self, boxID, rbtID, dMaxLineVel, dMaxOriVel):
        result = []
        command = 'SetPoseTrackingMaxMotionLimit,'
        command += str(rbtID) + ','
        command += str(dMaxLineVel) + ','
        command += str(dMaxOriVel) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 2
    *	@param brief: Set location tracking timeout stop time
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dTime: time out
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetPoseTrackingStopTimeOut(self, boxID, rbtID, dTime):
        result = []
        command = 'SetPoseTrackingStopTimeOut,'
        command += str(rbtID) + ','
        command += str(dTime) + ',;'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Set PID of tracking position
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dPosPID1: Follow position PID
    *	@param dPosPID2: Follow position PID
    *	@param dPosPID3: Follow position PID
    *	@param dOriPID1: Follow angular PID
    *	@param dOriPID2: Follow angular PID
    *	@param dOriPID3: Follow angular PID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetPoseTrackingPIDParams(self, boxID, rbtID, dPosPID1, dPosPID2, dPosPID3, dOriPID1, dOriPID2, dOriPID3):
        result = []
        command = 'SetPoseTrackingPIDParams,'
        command += str(rbtID) + ','
        command += str(dPosPID1) + ','
        command += str(dPosPID2) + ','
        command += str(dPosPID3) + ','
        command += str(dOriPID1) + ','
        command += str(dOriPID2) + ','
        command += str(dOriPID3) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 4
    *	@param brief: Set target of tracking position
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dX: Distance maintained in the X direction
    *	@param dY: Distance maintained in the Y direction
    *	@param dZ: Distance maintained in the Z direction
    *	@param dRx: Distance maintained in the Rx direction
    *	@param dRy: Distance maintained in the Ry direction
    *	@param dRz: Distance maintained in the Rz direction
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetPoseTrackingTargetPos(self, boxID, rbtID, dX, dY, dZ, dRx, dRy, dRz):
        result = []
        command = 'SetPoseTrackingTargetPos,'
        command += str(rbtID) + ','
        command += str(dX) + ','
        command += str(dY) + ','
        command += str(dZ) + ','
        command += str(dRx) + ','
        command += str(dRy) + ','
        command += str(dRz) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 5
    *	@param brief: Set state of tracking position
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nState: Tracking state
    *                              0: Disable tracking position
    *                              1: Enable tracking position
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetPoseTrackingState(self, boxID, rbtID, nState):
        result = []
        command = 'SetPoseTrackingState,'
        command += str(rbtID) + ','
        command += str(nState) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 6
    *	@param brief: Set real time position update of tracking position
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param dX: Checking distance for X
    *	@param dY: Checking distance for Y
    *	@param dZ: Checking distance for Z
    *	@param dRx: Checking distance for Rx
    *	@param dRy: Checking distance for Ry
    *	@param dRz: Checking distance for Rz
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_SetUpdateTrackingPose(self, boxID, rbtID, dX, dY, dZ, dRx, dRy, dRz):
        result = []
        command = 'SetUpdateTrackingPose,'
        command += str(rbtID) + ','
        command += str(dX) + ','
        command += str(dY) + ','
        command += str(dZ) + ','
        command += str(dRx) + ','
        command += str(dRy) + ','
        command += str(dRz) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    #
    # part 15 Interforces for other
    #

    '''
    *	@index : 1
    *	@param brief: Excute HRApp command
    *	@param boxID: Control box ID
    *	@param name : HRAppName
    *	@param param: Command name and paramters
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_HRAppCmd(self, boxID, name, cmd, param, result):
        command = 'HRAppCmd,'
        command += str(name) + ','
        command += str(cmd) + ','
        for i in range(len(param)):
            command += str(param[i]) + ','
        command += ';'
        if self.isV8CPS and self.g_plugin_client_state[boxID]:
            return self.g_plugin_clients[boxID].sendAndRecv(command, result)
        elif self.isV8CPS and not self.g_plugin_client_state[boxID]:
            print("Unable to connect to plugin service")
            return 39504
        else:
            return self.g_clients[boxID].sendAndRecv(command, result)
    
    def HRIF_HRApp(self, boxID, name, cmd, param, result):
        self.HRIF_HRAppCmd(boxID, name, cmd, param, result)

    '''
    *	@index : 2
    *	@param brief: Write End holding registers of Modbus slave
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nSlaveID: Modbus Slave ID
    *	@param nFunction: Function code
    *	@param nRegAddr: Register beginning address
    *	@param nRegCount: Registers number, maximum 11
    *	@param data : Registers value, with the registers size of nRegCount
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_WriteEndHoldingRegisters(self, boxID, rbtID, nSlaveID, nFunction, nRegAddr, nRegCount, data):
        result = []
        command = 'WriteHoldingRegisters,'
        command += str(rbtID) + ','
        command += str(nSlaveID) + ','
        command += str(nFunction) + ','
        command += str(nRegAddr) + ','
        command += str(nRegCount) + ','
        if nRegCount != len(data):
            return ['-1']
        for i in range(nRegCount):
            command += str(data[i]) + ','
        command += ';'
        return self.g_clients[boxID].sendAndRecv(command, result)

    '''
    *	@index : 3
    *	@param brief: Read End holding registers of Modbus slave
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	@param nSlaveID: Modbus slave ID
    *	@param nFunction: Function code
    *                            0x01-Read coil register
    *                            0x02-Read line discrete input register
    *                            0x03-Read holding register
    *                            0x04-Read input register
    *                            0x05-Write signle coil register
    *                            0x06-Write signle holding register
    *                            0x0f-Write multiple coil register
    *                            0x10-Write multiple holding register
    *	@param nRegAddr: Register beginning address
    *	@param nRegCount: Registers number, maximum 12
    *	@param retData[1-n]: obtained registers value, with the registers size of nRegCount
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def HRIF_ReadEndHoldingRegisters(self, boxID, rbtID, nSlaveID, nFunction, nRegAddr, nRegCount, result):
        command = 'ReadHoldingRegisters,'
        command += str(rbtID) + ','
        command += str(nSlaveID) + ','
        command += str(nFunction) + ','
        command += str(nRegAddr) + ','
        command += str(nRegCount) + ',;'
        retData = self.g_clients[boxID].sendAndRecv(command, result)
        return retData

    '''
    *	@index : 4
    *	@param brief: Wait for robot stop moving 
    *	@param boxID: Control box ID
    *	@param rbtID: Robot ID
    *	
    *	@return : nRet=0 : Function call succeeded
    *             nRet>0 : Error code of function call
    '''
    def waitMovementDone(self, boxID, rbtID, result):
        while True:
            command = 'ReadCurFSM,'
            command += str(rbtID) + ','
            command += ';'
            retData = self.g_clients[boxID].sendAndRecv(command, result)
            if retData != 0:
                return retData
            if not result:
                return 39505
            if int(result[0]) == 25:
                time.sleep(0.1)
                continue
            else:
                break
        return 0

    
# sendVarValue
# No output

def ReadFloat(*args, reverse=False):
    for n, m in args:
        n, m = '%04x' % n, '%04x' % m
    if reverse:
        v = n + m
    else:
        v = m + n
    y_bytes = bytes.fromhex(v)
    y = struct.unpack('!f', y_bytes)[0]
    y = round(y, 6)
    return y


def WriteFloat(value, reverse=False):
    print(WriteFloat)
    y_bytes = struct.pack('!f', value)
    print(y_bytes)
    y_hex = ''.join(['%02x' % i for i in y_bytes])
    print(y_hex)
    n, m = y_hex[:-4], y_hex[-4:]
    n, m = int(n, 16), int(m, 16)
    if reverse:
        v = [n, m]
    else:
        v = [m, n]
    return v


def ReadDint(*args, reverse=False, result):
    for n, m in args:
        n, m = '%04x' % n, '%04x' % m
    if reverse:
        v = n + m
    else:
        v = m + n
    y_bytes = bytes.fromhex(v)
    y = struct.unpack('!i', y_bytes)[0]
    return y


def WriteDint(value, reverse=False):
    y_bytes = struct.pack('!i', value)
    # y_hex = bytes.hex(y_bytes)
    y_hex = ''.join(['%02x' % i for i in y_bytes])
    n, m = y_hex[:-4], y_hex[-4:]
    n, m = int(n, 16), int(m, 16)
    if reverse:
        v = [n, m]
    else:
        v = [m, n]
    return v
