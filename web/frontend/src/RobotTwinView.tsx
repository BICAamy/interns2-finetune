import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import type { RobotRenderPose, SimulationTelemetry } from "./types";

type CameraPreset = "front" | "left" | "right" | "top" | "isometric";

interface RobotTwinViewProps {
  telemetry: SimulationTelemetry | null;
  runtimeMode: "simulation" | "real";
  workspaceLow?: [number, number, number] | null;
  workspaceHigh?: [number, number, number] | null;
  onReady?: () => void;
  onError?: (message: string) => void;
}

const MODEL_FILES = [
  "elfin_base.STL",
  "elfin_link1.STL",
  "elfin_link2.STL",
  "elfin_link3.STL",
  "elfin_link4.STL",
  "elfin_link5.STL",
  "elfin_link6.STL",
];

const CAMERA_TARGET = new THREE.Vector3(0.35, 0, 0.42);
const CAMERA_PRESETS: Record<CameraPreset, [number, number, number]> = {
  front: [0, 0, 2.1],
  left: [-90, 0, 2.1],
  right: [90, 0, 2.1],
  top: [0, 82, 1.75],
  isometric: [38, 28, 1.85],
};
const PRESET_LABELS: Array<[CameraPreset, string]> = [
  ["front", "正视"],
  ["left", "左视"],
  ["right", "右视"],
  ["top", "俯视"],
  ["isometric", "等轴测"],
];

function applyPose(object: any, pose: RobotRenderPose, immediate: boolean) {
  const targetPosition = new THREE.Vector3(...pose.position_m);
  const [x, y, z, w] = pose.quaternion_xyzw;
  const targetQuaternion = new THREE.Quaternion(x, y, z, w).normalize();
  object.userData.targetPosition = targetPosition;
  object.userData.targetQuaternion = targetQuaternion;
  if (immediate) {
    object.position.copy(targetPosition);
    object.quaternion.copy(targetQuaternion);
    object.userData.hasPose = true;
  }
}

function cameraPosition(yawDeg: number, pitchDeg: number, distance: number) {
  const yaw = THREE.MathUtils.degToRad(yawDeg);
  const pitch = THREE.MathUtils.degToRad(pitchDeg);
  return CAMERA_TARGET.clone().add(
    new THREE.Vector3(
      Math.sin(yaw) * Math.cos(pitch),
      -Math.cos(yaw) * Math.cos(pitch),
      Math.sin(pitch),
    ).multiplyScalar(distance),
  );
}

export default function RobotTwinView({
  telemetry,
  runtimeMode,
  workspaceLow,
  workspaceHigh,
  onReady,
  onError,
}: RobotTwinViewProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const linksRef = useRef<any[]>([]);
  const tcpMarkerRef = useRef<any>(null);
  const entryMarkerRef = useRef<any>(null);
  const targetMarkerRef = useRef<any>(null);
  const trajectoryRef = useRef<any>(null);
  const workspaceRef = useRef<any>(null);
  const cameraRef = useRef<any>(null);
  const controlsRef = useRef<any>(null);
  const trajectorySignatureRef = useRef("");
  const [loaded, setLoaded] = useState(false);
  const [activePreset, setActivePreset] = useState<CameraPreset | "custom">("front");
  const [cameraLabel, setCameraLabel] = useState("方位 0° · 俯仰 0° · 2.10 m");

  const setCameraPreset = (preset: CameraPreset) => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;
    const [yaw, pitch, distance] = CAMERA_PRESETS[preset];
    camera.position.copy(cameraPosition(yaw, pitch, distance));
    camera.up.set(0, 0, 1);
    controls.target.copy(CAMERA_TARGET);
    controls.update();
    setActivePreset(preset);
    setCameraLabel(`方位 ${yaw}° · 俯仰 ${pitch}° · ${distance.toFixed(2)} m`);
  };

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let animationFrame = 0;
    let resizeObserver: ResizeObserver | null = null;
    const disposables: any[] = [];

    try {
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0xf8fafc);
      const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 8);
      camera.up.set(0, 0, 1);
      camera.position.copy(cameraPosition(0, 0, 2.1));
      cameraRef.current = camera;

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.15;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.domElement.setAttribute("aria-label", "浏览器本地渲染的 E05-Pro 数字孪生");
      host.appendChild(renderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.copy(CAMERA_TARGET);
      controls.enableDamping = true;
      controls.dampingFactor = 0.1;
      controls.screenSpacePanning = true;
      controls.minDistance = 0.65;
      controls.maxDistance = 4.5;
      controls.maxPolarAngle = Math.PI - 0.04;
      controls.update();
      controlsRef.current = controls;

      scene.add(new THREE.HemisphereLight(0xffffff, 0x9bb3c9, 2.25));
      const keyLight = new THREE.DirectionalLight(0xffffff, 3.0);
      keyLight.position.set(-1.5, -1.6, 2.7);
      keyLight.castShadow = true;
      scene.add(keyLight);
      const fillLight = new THREE.DirectionalLight(0x9bd9ff, 1.6);
      fillLight.position.set(1.8, 1.2, 1.3);
      scene.add(fillLight);

      const grid = new THREE.GridHelper(2.4, 24, 0xb8d8ec, 0xdbeaf4);
      grid.rotation.x = Math.PI / 2;
      grid.position.z = 0;
      (grid.material as any).transparent = true;
      (grid.material as any).opacity = 0.36;
      scene.add(grid);
      disposables.push(grid.geometry, grid.material);

      const axes = new THREE.AxesHelper(0.24);
      scene.add(axes);
      disposables.push(axes.geometry, axes.material);

      const trajectoryMaterial = new THREE.LineBasicMaterial({
        color: 0xf59e0b,
        linewidth: 2,
        transparent: true,
        opacity: 0.96,
      });
      const trajectory = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([]),
        trajectoryMaterial,
      );
      trajectory.renderOrder = 5;
      scene.add(trajectory);
      trajectoryRef.current = trajectory;
      disposables.push(trajectoryMaterial);

      const markerGeometry = new THREE.SphereGeometry(0.012, 22, 16);
      const makeMarker = (color: number, radiusScale = 1) => {
        const marker = new THREE.Mesh(
          markerGeometry,
          new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.25 }),
        );
        marker.scale.setScalar(radiusScale);
        marker.visible = false;
        scene.add(marker);
        disposables.push(marker.material);
        return marker;
      };
      tcpMarkerRef.current = makeMarker(0x16c784, 1.05);
      entryMarkerRef.current = makeMarker(0x2563eb, 0.9);
      targetMarkerRef.current = makeMarker(0xef4444, 0.9);
      disposables.push(markerGeometry);

      const silver = new THREE.MeshStandardMaterial({
        color: 0xc4cad1,
        metalness: 0.38,
        roughness: 0.3,
      });
      const dark = new THREE.MeshStandardMaterial({
        color: 0x333b46,
        metalness: 0.25,
        roughness: 0.42,
      });
      disposables.push(silver, dark);

      const loader = new STLLoader();
      Promise.all(MODEL_FILES.map((name) => loader.loadAsync(`/robot-assets/e05/${name}`)))
        .then((geometries: any[]) => {
          if (disposed) {
            geometries.forEach((geometry) => geometry.dispose());
            return;
          }
          const meshes = geometries.map((geometry, index) => {
            geometry.computeVertexNormals();
            const material = index === 0 || index % 2 === 0 ? dark : silver;
            const mesh = new THREE.Mesh(geometry, material);
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            if (index === 6) mesh.scale.z = 184 / 146;
            scene.add(mesh);
            disposables.push(geometry);
            return mesh;
          });
          linksRef.current = meshes.slice(1);
          setLoaded(true);
          onReady?.();
        })
        .catch((error: unknown) => {
          if (disposed) return;
          const message = `E05-Pro 模型加载失败：${error instanceof Error ? error.message : String(error)}`;
          setLoaded(false);
          onError?.(message);
        });

      let lastCameraUpdate = 0;
      const updateCameraLabel = () => {
        setActivePreset("custom");
        const now = performance.now();
        if (now - lastCameraUpdate < 100) return;
        lastCameraUpdate = now;
        const offset = camera.position.clone().sub(controls.target);
        const distance = offset.length();
        const yaw = THREE.MathUtils.radToDeg(Math.atan2(offset.x, -offset.y));
        const pitch = THREE.MathUtils.radToDeg(Math.asin(offset.z / Math.max(distance, 1e-9)));
        setCameraLabel(`方位 ${yaw.toFixed(0)}° · 俯仰 ${pitch.toFixed(0)}° · ${distance.toFixed(2)} m`);
      };
      controls.addEventListener("start", () => setActivePreset("custom"));
      controls.addEventListener("change", updateCameraLabel);
      const handleDoubleClick = () => setCameraPreset("front");
      renderer.domElement.addEventListener("dblclick", handleDoubleClick);

      const resize = () => {
        const width = Math.max(host.clientWidth, 1);
        const height = Math.max(host.clientHeight, 1);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height, false);
      };
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(host);
      resize();

      const clock = new THREE.Clock();
      const animate = () => {
        if (disposed) return;
        animationFrame = window.requestAnimationFrame(animate);
        const delta = Math.min(clock.getDelta(), 0.05);
        const blend = 1 - Math.exp(-18 * delta);
        for (const link of linksRef.current) {
          if (!link.userData.hasPose) continue;
          link.position.lerp(link.userData.targetPosition, blend);
          link.quaternion.slerp(link.userData.targetQuaternion, blend);
        }
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      return () => {
        disposed = true;
        window.cancelAnimationFrame(animationFrame);
        resizeObserver?.disconnect();
        renderer.domElement.removeEventListener("dblclick", handleDoubleClick);
        controls.dispose();
        for (const value of disposables) value?.dispose?.();
        trajectory.geometry.dispose();
        renderer.dispose();
        renderer.forceContextLoss();
        renderer.domElement.remove();
        linksRef.current = [];
        cameraRef.current = null;
        controlsRef.current = null;
      };
    } catch (error) {
      const message = `无法启动浏览器 3D 渲染：${error instanceof Error ? error.message : String(error)}`;
      setLoaded(false);
      onError?.(message);
    }
  }, []);

  useEffect(() => {
    if (telemetry?.render_link_poses?.length !== 6 || linksRef.current.length !== 6) return;
    telemetry.render_link_poses.forEach((pose, index) => {
      const link = linksRef.current[index];
      applyPose(link, pose, !link.userData.hasPose);
    });
  }, [loaded, telemetry?.sequence, telemetry?.render_link_poses]);

  useEffect(() => {
    const updatePoint = (marker: any, point: { x: number; y: number; z: number } | null) => {
      if (!marker) return;
      marker.visible = Boolean(point);
      if (point) marker.position.set(point.x / 1000, point.y / 1000, point.z / 1000);
    };
    updatePoint(tcpMarkerRef.current, telemetry?.current_tcp ?? null);
    updatePoint(entryMarkerRef.current, telemetry?.entry_point ?? null);
    updatePoint(targetMarkerRef.current, telemetry?.target_point ?? null);

    const points = telemetry?.trajectory_mm ?? [];
    const last = points.length ? points[points.length - 1] : undefined;
    const signature = `${telemetry?.trajectory_total_points ?? 0}:${points.length}:${last?.join(",") ?? ""}`;
    if (trajectoryRef.current && signature !== trajectorySignatureRef.current) {
      const geometry = new THREE.BufferGeometry().setFromPoints(
        points.map(([x, y, z]) => new THREE.Vector3(x / 1000, y / 1000, z / 1000)),
      );
      trajectoryRef.current.geometry.dispose();
      trajectoryRef.current.geometry = geometry;
      trajectorySignatureRef.current = signature;
    }
  }, [telemetry]);

  useEffect(() => {
    const mesh = linksRef.current[0];
    const scene = mesh?.parent;
    if (!scene || !workspaceLow || !workspaceHigh) return;
    const size = new THREE.Vector3(
      (workspaceHigh[0] - workspaceLow[0]) / 1000,
      (workspaceHigh[1] - workspaceLow[1]) / 1000,
      (workspaceHigh[2] - workspaceLow[2]) / 1000,
    );
    const center = new THREE.Vector3(
      (workspaceHigh[0] + workspaceLow[0]) / 2000,
      (workspaceHigh[1] + workspaceLow[1]) / 2000,
      (workspaceHigh[2] + workspaceLow[2]) / 2000,
    );
    const geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x, size.y, size.z));
    const material = new THREE.LineBasicMaterial({ color: 0xef7d88, transparent: true, opacity: 0.5 });
    const box = new THREE.LineSegments(geometry, material);
    box.position.copy(center);
    scene.add(box);
    workspaceRef.current = box;
    return () => {
      scene.remove(box);
      geometry.dispose();
      material.dispose();
      if (workspaceRef.current === box) workspaceRef.current = null;
    };
  }, [loaded, workspaceLow, workspaceHigh]);

  return (
    <div ref={hostRef} className="robot-twin-canvas" data-mode={runtimeMode}>
      {!loaded && <div className="robot-twin-loading">正在加载本地 E05-Pro 3D 模型…</div>}
      <div className="camera-hint">左键旋转 · 右键平移 · 滚轮缩放 · 双击复位</div>
      <div className="camera-state">{cameraLabel}</div>
      <div className="camera-presets" onPointerDown={(event) => event.stopPropagation()}>
        {PRESET_LABELS.map(([preset, label]) => (
          <button
            key={preset}
            className={activePreset === preset ? "active" : ""}
            onClick={() => setCameraPreset(preset)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
