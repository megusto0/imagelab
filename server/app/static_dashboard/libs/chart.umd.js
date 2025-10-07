(function () {
  function ChartStub(ctx, config) {
    this.ctx = ctx;
    this.config = config;
  }
  ChartStub.prototype.update = function update() {
    return true;
  };
  window.Chart = ChartStub;
})();
