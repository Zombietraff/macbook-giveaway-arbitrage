import { useState } from 'react';
import WebApp from '@twa-dev/sdk';
import useGame from '../../stores/store';
import { t } from '../../i18n';
import './style.css';

const DisclaimerModal = () => {
  const { languageCode, setDisclaimerAccepted } = useGame((state) => state);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  const handleAccept = async () => {
    if (isSaving) return;

    setIsSaving(true);
    setError('');

    try {
      const response = await fetch('/api/disclaimer/accept', {
        method: 'POST',
        headers: {
          Authorization: `tma ${WebApp.initData}`,
        },
      });
      const data = await response.json();

      if (!response.ok || data.disclaimerAccepted !== true) {
        throw new Error(data.error || 'disclaimer_accept_failed');
      }

      setDisclaimerAccepted(true);
    } catch (err) {
      console.error(err);
      setError(t(languageCode, 'disclaimerError'));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="disclaimer-modal" role="dialog" aria-modal="true">
      <div className="disclaimer-box">
        <h2>{t(languageCode, 'disclaimerTitle')}</h2>
        <p>{t(languageCode, 'disclaimerText')}</p>
        {error && <div className="disclaimer-error">{error}</div>}
        <button
          className="disclaimer-accept"
          type="button"
          onClick={handleAccept}
          disabled={isSaving}
        >
          {isSaving
            ? t(languageCode, 'disclaimerSaving')
            : t(languageCode, 'disclaimerAccept')}
        </button>
      </div>
    </div>
  );
};

export default DisclaimerModal;
