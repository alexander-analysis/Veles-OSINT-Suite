import { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Polygon, Popup, Tooltip, useMap, useMapEvents, LayersControl, LayerGroup, Polyline, Marker } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Link } from 'react-router-dom';
import { useFetch } from '../../hooks/useFetch';

const AUTHORITY_STYLE = {
  ofac: { color: '#e74c3c', fillColor: '#e74c3c', fillOpacity: 0.06, weight: 1.5 },
  eu: { color: '#3498db', fillColor: '#3498db', fillOpacity: 0.06, weight: 1.5 },
  un: { color: '#f1c40f', fillColor: '#f1c40f', fillOpacity: 0.08, weight: 1.5 },
  other: { color: '#7f8c8d', fillColor: '#7f8c8d', fillOpacity: 0.05, weight: 1, dashArray: '4 4' },
};

const ring = (feature) => feature.geometry.coordinates[0].map(([lon, lat]) => [lat, lon]);

function InvalidateOnMount() {
  // The container is laid out after Leaflet measures it (cards, tabs, fonts loading) - re-measure once settled.
  const map = useMap();
  useEffect(() => {
    const timers = [50, 300, 1000].map((ms) => setTimeout(() => map.invalidateSize(), ms));
    const onResize = () => map.invalidateSize();
    window.addEventListener('resize', onResize);
    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener('resize', onResize);
    };
  }, [map]);
  return null;
}

function ViewportWatcher({ onViewChange }) {
  // Report the visible bbox (padded) after every pan/zoom so the page can fetch just that area.
  const map = useMapEvents({
    moveend: () => report(),
    zoomend: () => report(),
  });
  const report = () => {
    if (!onViewChange) return;
    const b = map.getBounds().pad(0.15);
    onViewChange({
      zoom: map.getZoom(),
      bbox: [Math.max(-180, b.getWest()), Math.max(-90, b.getSouth()), Math.min(180, b.getEast()), Math.min(90, b.getNorth())].map((n) => Number(n.toFixed(3))),
    });
  };
  const initial = useRef(false);
  useEffect(() => {
    if (initial.current) return undefined;
    initial.current = true;
    const t = setTimeout(report, 1200);
    return () => clearTimeout(t);
  });
  return null;
}

function FitOnce({ features }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (done.current || !features?.length) return;
    const bounds = L.latLngBounds(features.map((f) => [f.geometry.coordinates[1], f.geometry.coordinates[0]]));
    if (bounds.isValid()) {
      map.fitBounds(bounds.pad(0.2), { maxZoom: 8 });
      done.current = true;
    }
  }, [features, map]);
  return null;
}

function ZoneLayer({ features, styleKey }) {
  return features.map((f, i) => (
    <Polygon key={`${styleKey}-${i}`} positions={ring(f)} pathOptions={AUTHORITY_STYLE[styleKey]}>
      <Tooltip sticky>
        <b>{f.properties.name}</b>
        <br />
        {f.properties.kind?.replace('_', ' ')}
        {f.properties.authorities?.length ? ` - ${f.properties.authorities.join(', ')}` : ''}
        {f.properties.context ? <><br />{f.properties.context}</> : null}
      </Tooltip>
    </Polygon>
  ));
}

const breachIcon = (severity) =>
  L.divIcon({
    className: 'breach-marker',
    html: `<div style="background:${severity === 'critical' ? '#8b0000' : '#e74c3c'};width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.3)">!</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });

/**
 * Interactive vessel map: OSM tiles, colour-coded vessel markers, breach markers,
 * sanctions/monitoring zones by authority, lanes/chokepoints, ports and an optional track.
 */
export default function VesselMap({ vessels, breaches, selectedTrack, height = '600px', center = [60, 24], zoom = 6, onViewChange, fitToData = true }) {
  const { data: zones } = useFetch('/api/maritime/sanctions-zones', 0);
  const { data: lanes } = useFetch('/api/maritime/shipping-lanes', 0);
  const { data: ports } = useFetch('/api/maritime/ports', 0);
  const [showClear, setShowClear] = useState(true);
  const features = vessels?.features || [];
  const visible = useMemo(() => (showClear ? features : features.filter((f) => f.properties.sanctioned_status !== 'clear')), [features, showClear]);

  return (
    <div className="relative" style={{ height }}>
      <div className="absolute z-[1000] top-2 right-14 bg-white/90 border border-gray-300 rounded px-2 py-1 text-xs flex items-center gap-3 shadow-sm">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={showClear} onChange={(e) => setShowClear(e.target.checked)} /> show clear vessels
        </label>
        <span className="flex items-center gap-1"><i className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: '#2ecc71' }} /> clear</span>
        <span className="flex items-center gap-1"><i className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: '#f39c12' }} /> flagged</span>
        <span className="flex items-center gap-1"><i className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: '#e74c3c' }} /> breach</span>
      </div>
      <MapContainer center={center} zoom={zoom} style={{ height: '100%', width: '100%' }} preferCanvas>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' maxZoom={19} />
        <InvalidateOnMount />
        {fitToData && <FitOnce features={features} />}
        {onViewChange && <ViewportWatcher onViewChange={onViewChange} />}
        <LayersControl position="topright">
          <LayersControl.Overlay checked name="OFAC zones">
            <LayerGroup>{zones?.ofac && <ZoneLayer features={zones.ofac.features} styleKey="ofac" />}</LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay checked name="EU zones">
            <LayerGroup>{zones?.eu && <ZoneLayer features={zones.eu.features} styleKey="eu" />}</LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay checked name="UN zones">
            <LayerGroup>{zones?.un && <ZoneLayer features={zones.un.features} styleKey="un" />}</LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay name="War / piracy zones">
            <LayerGroup>{zones?.other && <ZoneLayer features={zones.other.features} styleKey="other" />}</LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay checked name="Shipping lanes / chokepoints">
            <LayerGroup>
              {lanes?.lanes?.features?.map((f, i) => (
                <Polygon key={`lane-${i}`} positions={ring(f)} pathOptions={{ color: f.properties.choke_point ? '#c0392b' : '#3498db', dashArray: '5 5', weight: 1.5, fillOpacity: 0.02 }}>
                  <Tooltip sticky>{f.properties.name}{f.properties.choke_point ? ' (chokepoint)' : ''}</Tooltip>
                </Polygon>
              ))}
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay name="Ports">
            <LayerGroup>
              {ports?.features?.map((f) => (
                <CircleMarker
                  key={f.properties.unlocode}
                  center={[f.geometry.coordinates[1], f.geometry.coordinates[0]]}
                  radius={5}
                  pathOptions={{ color: '#2f4a6b', fillColor: f.properties.risk_level === 'high' ? '#e74c3c' : f.properties.risk_level === 'medium' ? '#f39c12' : '#4a6fa5', fillOpacity: 0.9, weight: 1 }}
                >
                  <Tooltip>
                    <b>{f.properties.name}</b> ({f.properties.country}) - {f.properties.risk_level}
                    {f.properties.note ? <><br />{f.properties.note}</> : null}
                  </Tooltip>
                </CircleMarker>
              ))}
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay checked name="Vessels">
            <LayerGroup>
              {visible.map((f) => {
                const p = f.properties;
                return (
                  <CircleMarker
                    key={p.mmsi}
                    center={[f.geometry.coordinates[1], f.geometry.coordinates[0]]}
                    radius={p.sanctioned_status === 'clear' ? 4 : 7}
                    pathOptions={{ color: '#111', weight: 0.6, fillColor: p.marker_color, fillOpacity: 0.85 }}
                  >
                    <Popup>
                      <div className="text-xs leading-5">
                        <b>{p.name}</b> {p.flag && <span>({p.flag})</span>}
                        <br />MMSI {p.mmsi}{p.imo ? ` - IMO ${p.imo}` : ''}
                        <br />{p.ship_type || 'unknown type'}{p.destination ? ` - to ${p.destination}` : ''}
                        <br />Speed {p.speed ?? '-'} kn - {p.ais_status || 'status n/a'}
                        <br />Status <b>{p.sanctioned_status}</b> - risk {p.risk_score != null ? `${Math.round(p.risk_score * 100)}%` : 'n/a'}
                        <br />Source {p.ais_source} - {p.last_update ? new Date(p.last_update).toLocaleTimeString() : ''}
                        <br /><Link to={`/maritime/vessel/${p.mmsi}`} className="text-steel-600 underline">View details</Link>
                      </div>
                    </Popup>
                  </CircleMarker>
                );
              })}
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay checked name="Breach alerts">
            <LayerGroup>
              {(breaches || []).filter((b) => b.location?.lat != null).map((b) => (
                <Marker key={`breach-${b.id}`} position={[b.location.lat, b.location.lon]} icon={breachIcon(b.severity)}>
                  <Popup>
                    <div className="text-xs leading-5">
                      <b>BREACH - {b.sanctioning_authority}</b>
                      <br />{b.vessel_name} ({b.flag}) - {b.breach_type.replace('_', ' ')}
                      <br />{b.sanctioned_entity} - confidence {Math.round((b.match_confidence || 0) * 100)}%
                      <br />Status {b.investigation_status}
                      <br /><Link to={`/maritime/vessel/${b.mmsi}`} className="text-steel-600 underline">Investigate</Link>
                    </div>
                  </Popup>
                </Marker>
              ))}
            </LayerGroup>
          </LayersControl.Overlay>
        </LayersControl>
        {selectedTrack?.length > 1 && <Polyline positions={selectedTrack.map((p) => [p.lat, p.lon])} pathOptions={{ color: '#2f4a6b', weight: 2 }} />}
      </MapContainer>
    </div>
  );
}
