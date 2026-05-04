import useGame from '../../stores/store';
import { t } from '../../i18n';
import './style.css';

const HelpModal = () => {
  const { setModal, showBars, toggleBars, languageCode } = useGame((state) => state);

  return (
    <div className="modal" onClick={() => setModal(false)}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-main">
          <div className="modal-text">
            {t(languageCode, 'helpIntro')}
          </div>
          <div className="modal-text">
            {t(languageCode, 'helpMatch')}
          </div>
          <div className="modal-text">
            {t(languageCode, 'helpLocked')}
          </div>
          <div id="paytable">
            <div className="modal-text">
              <img className="modal-image" src="./images/cherry.png" />
              <img className="modal-image" src="./images/cherry.png" />
              <img className="modal-image" src="./images/cherry.png" />
              <span>{t(languageCode, 'payout')} 50</span>
              <img className="modal-image" src="./images/coin.png" />
            </div>
            <div className="modal-text">
              <img className="modal-image" src="./images/apple.png" />
              <img className="modal-image" src="./images/apple.png" />
              <img className="modal-image" src="./images/apple.png" />
              <span>{t(languageCode, 'payout')} 20</span>
              <img className="modal-image" src="./images/coin.png" />
            </div>
            <div className="modal-text">
              <img className="modal-image" src="./images/banana.png" />
              <img className="modal-image" src="./images/banana.png" />
              <img className="modal-image" src="./images/banana.png" />
              <span>{t(languageCode, 'payout')} 15</span>
              <img className="modal-image" src="./images/coin.png" />
            </div>
            <div className="modal-text">
              <img className="modal-image" src="./images/lemon.png" />
              <img className="modal-image" src="./images/lemon.png" />
              <img className="modal-image" src="./images/lemon.png" />
              <span>{t(languageCode, 'payout')} 5</span>
              <img className="modal-image" src="./images/coin.png" />
            </div>
            <div className="modal-text">
              <img className="modal-image" src="./images/cherry.png" />
              <img className="modal-image" src="./images/cherry.png" />
              <span>{t(languageCode, 'payout')} 40</span>
              <img className="modal-image" src="./images/coin.png" />
            </div>
            <div className="modal-text">
              <img className="modal-image" src="./images/apple.png" />
              <img className="modal-image" src="./images/apple.png" />
              <span>{t(languageCode, 'payout')} 10</span>
              <img className="modal-image" src="./images/coin.png" />
            </div>
            <div className="modal-text">
              <img className="modal-image" src="./images/banana.png" />
              <img className="modal-image" src="./images/banana.png" />
              <span>{t(languageCode, 'payout')} 5</span>
              <img className="modal-image" src="./images/coin.png" />
            </div>
          </div>

          <button onClick={toggleBars}>
            {showBars
              ? t(languageCode, 'hideBars')
              : t(languageCode, 'showBars')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default HelpModal;
