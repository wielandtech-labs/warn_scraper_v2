// react-leaflet's default marker icons don't resolve correctly under Vite's
// bundler, so we point Leaflet at explicit CDN asset URLs. Importing this module
// for its side effect sets the default icon process-wide; shared by every map.
import L from "leaflet";

export const DefaultIcon = L.icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});

L.Marker.prototype.options.icon = DefaultIcon;
