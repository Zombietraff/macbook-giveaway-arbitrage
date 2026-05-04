import * as React from 'react';
import * as THREE from 'three';
import { useGLTF } from '@react-three/drei';
import { GLTF } from 'three-stdlib';
import { Text } from '@react-three/drei';
import useGame from './stores/store';
import { t } from './i18n';

type GLTFResult = GLTF & {
  nodes: {
    Cube_Subscribe_0: THREE.Mesh;
  };
};

const Button = (props: React.JSX.IntrinsicElements['group']) => {
  const { phase, languageCode } = useGame((state) => state);
  const label =
    phase === 'idle' ? t(languageCode, 'spin') : t(languageCode, 'spinning');

  const gltf = useGLTF('models/button.glb') as unknown as GLTFResult;
  const { nodes } = gltf;

  const material = new THREE.MeshStandardMaterial({ color: '#3b0873' });

  return (
    <group
      {...props}
      dispose={null}
      onPointerOver={() => {
        document.body.style.cursor = 'pointer';
      }}
      onPointerOut={() => {
        document.body.style.cursor = 'default';
      }}
    >
      <group
        position={[713.17, 1157.193, -723.814]}
        rotation={[-Math.PI / 2, 0, 0]}
        scale={[130.456, 19.364, 45.456]}
      >
        <mesh
          castShadow
          receiveShadow
          geometry={nodes.Cube_Subscribe_0.geometry}
          material={material}
          position={[-5.454, -37.484, -26.142]}
        ></mesh>
      </group>
      <Text
        color="white"
        anchorX="center"
        anchorY="middle"
        position={[0, -33, 22]}
        fontSize={phase === 'idle' ? 48 : 40}
        scale={[0.8, 1, 1]}
        font="./fonts/Nunito-Black.ttf"
      >
        {label}
      </Text>
    </group>
  );
};

useGLTF.preload('models/button.glb');
export default Button;
