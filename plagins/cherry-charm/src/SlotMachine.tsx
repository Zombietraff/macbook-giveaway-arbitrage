import {
  useRef,
  useEffect,
  forwardRef,
  useImperativeHandle,
  useState,
  useCallback,
} from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import useGame from './stores/store';
import segmentToFruit from './utils/functions/segmentToFruit';
import { WHEEL_SEGMENT } from './utils/constants';
import Reel from './Reel';
import Button from './Button';

import { getSegmentForFruit } from './utils/functions/fruitToSegment';
import { getTelegramAuthHeaders } from './utils/telegramAuth';

interface ReelGroup extends THREE.Group {
  reelSegment?: number;
  reelSpinUntil?: number;
  spinStartedAt?: number;
  spinDuration?: number;
  spinStartRotationX?: number;
  targetRotationX?: number;
}

interface SlotMachineProps {
  value: (0 | 1 | 2 | 3 | 4 | 5 | 6 | 7)[];
}

const REEL_BASE_SPINS = [2, 2, 3] as const;
const REEL_DURATIONS_MS = [1400, 1800, 2200] as const;
const FINALIZE_DELAY_MS = 300;

const easeOutCubic = (progress: number) => 1 - Math.pow(1 - progress, 3);

const SlotMachine = forwardRef(({ value }: SlotMachineProps, ref) => {
  const {
    fruit0,
    fruit1,
    fruit2,
    setFruit0,
    setFruit1,
    setFruit2,
    setWin,
    serverWinAmount,
    phase,
    start,
    end,
    addSpin,
    updateCoins,
    validateBet,
    disclaimerAccepted,
  } = useGame((state) => state);

  const reelRefs = [
    useRef<ReelGroup>(null),
    useRef<ReelGroup>(null),
    useRef<ReelGroup>(null),
  ];

  /**
   * Finalize round: calculate winnings, add to coins,
   * and validate if the bet is still affordable.
   */
  useEffect(() => {
    if (phase === 'idle' && fruit0 !== '' && fruit1 !== '' && fruit2 !== '') {
      const coinsWon = serverWinAmount;
      setWin(coinsWon);
      updateCoins(coinsWon);
      validateBet(); // Check affordability after coins are added back
    }
  }, [
    phase,
    fruit0,
    fruit1,
    fruit2,
    serverWinAmount,
    setWin,
    updateCoins,
    validateBet,
  ]);

  const handleSpinAction = useCallback(async () => {
    const currentState = useGame.getState();

    if (
      currentState.phase === 'spinning' ||
      currentState.coins < currentState.bet ||
      currentState.coins <= 1 ||
      currentState.bet > currentState.coins - 1 ||
      !currentState.disclaimerAccepted
    ) {
      return;
    }

    const currentBetAmount = currentState.bet;

    start(currentBetAmount);
    // Don't deduct coins manually yet, or we could optimistic update, but API will do it
    updateCoins(-currentBetAmount);
    addSpin();

    setWin(0);
    setFruit0('');
    setFruit1('');
    setFruit2('');

    try {
      const response = await fetch('/api/spin', {
        method: 'POST',
        headers: {
          ...getTelegramAuthHeaders(),
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ bet: currentBetAmount })
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        console.error("Spin failed:", data.error);
        // Revert coins if needed and stop
        updateCoins(currentBetAmount);
        useGame.getState().end();
        return;
      }
      
      const symbols = data.symbols; // e.g. ["CHERRY", "APPLE", "BANANA"]
      const winAmount = data.win;
      
      useGame.getState().setServerWinAmount(winAmount);
      
      for (let i = 0; i < 3; i++) {
        const reel = reelRefs[i].current;
        if (reel) {
          reel.rotation.x = 0;
          reel.reelSegment = 0;
          
          const stopSegment = getSegmentForFruit(
            i,
            symbols[i],
            REEL_BASE_SPINS[i],
          );
          
          reel.reelSpinUntil = stopSegment;
          reel.spinStartedAt = performance.now();
          reel.spinDuration = REEL_DURATIONS_MS[i];
          reel.spinStartRotationX = 0;
          reel.targetRotationX = stopSegment * WHEEL_SEGMENT;
        }
      }
    } catch (err) {
      console.error(err);
      updateCoins(currentBetAmount);
      useGame.getState().end();
    }
  }, [
    updateCoins,
    addSpin,
    setWin,
    start,
    setFruit0,
    setFruit1,
    setFruit2,
    disclaimerAccepted,
  ]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.code === 'Space') {
        event.preventDefault();
        handleSpinAction();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleSpinAction]);

  useFrame(() => {
    let spinningReels = 0;
    let completedReels = 0;

    for (let i = 0; i < reelRefs.length; i++) {
      const reel = reelRefs[i].current;
      if (
        !reel ||
        reel.reelSpinUntil === undefined ||
        reel.targetRotationX === undefined ||
        reel.spinStartedAt === undefined ||
        reel.spinDuration === undefined ||
        reel.spinStartRotationX === undefined
      )
        continue;

      spinningReels++;

      const elapsed = performance.now() - reel.spinStartedAt;
      const progress = Math.min(elapsed / reel.spinDuration, 1);
      const easedProgress = easeOutCubic(progress);

      reel.rotation.x = THREE.MathUtils.lerp(
        reel.spinStartRotationX,
        reel.targetRotationX,
        easedProgress,
      );
      reel.reelSegment = Math.floor(reel.rotation.x / WHEEL_SEGMENT);

      if (progress >= 1) {
        reel.rotation.x = reel.targetRotationX;
        const fruit = segmentToFruit(i, reel.reelSpinUntil);
        if (fruit) {
          if (i === 0) setFruit0(fruit);
          if (i === 1) setFruit1(fruit);
          if (i === 2) setFruit2(fruit);
        }

        reel.reelSpinUntil = undefined;
        reel.spinStartedAt = undefined;
        reel.spinDuration = undefined;
        reel.spinStartRotationX = undefined;
        reel.targetRotationX = undefined;
        completedReels++;
      }
    }

    if (spinningReels > 0 && spinningReels === completedReels) {
      setTimeout(() => end(), FINALIZE_DELAY_MS);
    }
  });

  useImperativeHandle(ref, () => ({ reelRefs }));

  const [buttonZ, setButtonZ] = useState(0);
  const [buttonY, setButtonY] = useState(-13);

  return (
    <>
      <Reel
        ref={reelRefs[0]}
        value={value[0]}
        map={0}
        position={[-7, 0, 0]}
        rotation={[0, 0, 0]}
        scale={[10, 10, 10]}
        reelSegment={0}
      />
      <Reel
        ref={reelRefs[1]}
        value={value[1]}
        map={1}
        position={[0, 0, 0]}
        rotation={[0, 0, 0]}
        scale={[10, 10, 10]}
        reelSegment={0}
      />
      <Reel
        ref={reelRefs[2]}
        value={value[2]}
        map={2}
        position={[7, 0, 0]}
        rotation={[0, 0, 0]}
        scale={[10, 10, 10]}
        reelSegment={0}
      />
      <Button
        scale={[0.055, 0.045, 0.045]}
        position={[0, buttonY, buttonZ]}
        rotation={[-Math.PI / 8, 0, 0]}
        onClick={(e) => {
          if (e.target instanceof HTMLElement) e.target.blur();
          handleSpinAction();
        }}
        onPointerDown={() => {
          setButtonZ(-1);
          setButtonY(-13.5);
        }}
        onPointerUp={() => {
          setButtonZ(0);
          setButtonY(-13);
        }}
      />
    </>
  );
});

export default SlotMachine;
