function TreeUtil() {
}

TreeUtil.calc_radius = function(scale) {
  var min_area = 700, max_area = 8000;
  var area = Util.calc_in_range(min_area, max_area, scale);
  return Math.sqrt(area / Math.PI);
}

TreeUtil.find_cluster_from_treeidx = function(tree_index, clusters){
  var clust_count = 0;
  var in_cluster = -1;
  Object.keys(clusters).forEach(function(cidx){
    clust_count = clust_count + 1;
    var cluster = clusters[cidx];
    if(cluster.members.indexOf(tree_index) != -1){
      in_cluster = clust_count;
      return;
    }
  });
  return in_cluster
}

TreeUtil.find_best_tree = function(densities) {
  var max_density = 0;
  var best_tidx = null;
  Object.keys(densities).forEach(function(tidx) {
    var density = densities[tidx];
    if(density > max_density) {
      max_density = density;
      best_tidx = tidx;
    }
  });
  if(best_tidx == null) {
    throw "best_tidx is null";
  }
  return parseInt(best_tidx, 10);
}