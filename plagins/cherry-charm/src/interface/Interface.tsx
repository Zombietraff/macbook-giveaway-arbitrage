import useGame from '../stores/store';
import HelpModal from './helpModal/HelpModal';
import HelpButton from './helpButton/HelpButton';
import useAnimatedNumber from '../hooks/useAnimatedNumber';
import { t } from '../i18n';
import './style.css';

const Interface = () => {
  const { modal, coins, win, bet, phase, updateBet, languageCode } = useGame(
    (state) => state,
  );
  const animatedCoins = useAnimatedNumber(coins);
  return (
    <>
      {/* Help Button */}
      <HelpButton />

      {/* Modal */}
      {modal && <HelpModal />}

      {/* Logo */}
      <div id="logo-section">
        <img className="logo" src="./images/logo.png" alt="" />
        {/* <div id="version">{__APP_VERSION__}</div> */}
      </div>

      <div className="interface">
        {/* Coins */}
        <div className="coins-section">
          <div className="coins-number">{animatedCoins}</div>
          <img className="coins-image" src="./images/coin.png" />
        </div>

        {/* Bet */}
        <div className="bet-section">
          <div className="bet-label">{t(languageCode, 'bet')}</div>
          <div className="bet-amount">{bet}</div>
          <div id="bet-controls" className={phase === 'idle' ? '' : 'hidden'}>
            <div
              id="increase-bet"
              className="bet-control"
              onClick={() => updateBet(1)}
            >
              +
            </div>
            <div
              id="decrease-bet"
              className="bet-control"
              onClick={() => updateBet(-1)}
            >
              -
            </div>
          </div>
        </div>

        {/* Spins */}
        <div className="win-section">
          <div className="win-label">{t(languageCode, 'win')}</div>
          <div className="win-amount">{win}</div>
        </div>
      </div>
    </>
  );
};

export default Interface;
