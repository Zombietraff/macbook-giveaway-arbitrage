import { Canvas } from '@react-three/fiber';
import Interface from './interface/Interface';
import DisclaimerModal from './interface/disclaimer/DisclaimerModal';
import Game from './Game';
import useGame from './stores/store';
import { useEffect } from 'react';
import WebApp from '@twa-dev/sdk';
import { normalizeLanguage } from './i18n';

const App = () => {
  const {
    isMobile,
    isUserLoaded,
    disclaimerAccepted,
    setCoins,
    setLanguageCode,
    setUserLoaded,
    setDisclaimerAccepted,
  } = useGame((state) => state);

  useEffect(() => {
    WebApp.ready();
    WebApp.expand();
    
    // Fetch initial balance
    const initData = WebApp.initData;
    fetch('/api/user', {
      headers: {
        'Authorization': `tma ${initData}`
      }
    })
    .then(res => res.json())
    .then(data => {
      if (data.coins !== undefined) {
        setCoins(data.coins);
      }
      setLanguageCode(normalizeLanguage(data.languageCode));
      setDisclaimerAccepted(data.disclaimerAccepted === true);
      setUserLoaded(true);
    })
    .catch(err => {
      console.error("Error fetching user data:", err);
      setUserLoaded(true);
    });
  }, [setCoins, setLanguageCode, setUserLoaded, setDisclaimerAccepted]);

  return (
    <>
      <Interface />
      {isUserLoaded && !disclaimerAccepted && <DisclaimerModal />}
      <div id="overlay"></div>
      <Canvas
        camera={{ fov: 75, position: [0, 0, isMobile ? 40 : 30] }}
        gl={{ alpha: true }}
        style={{ background: 'transparent' }}
      >
        <Game />
      </Canvas>
    </>
  );
};

export default App;
